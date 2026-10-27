import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, createPrivateKey } from 'node:crypto';
import worker, {chinaDate,pkcs8,setupToken} from './worker.mjs';

function environment() {
  const settings=new Map(); const events=[];
  return {ADMIN_KEY:'unit-test-admin-key',REPOSITORY:'TuringDong/news-digest',REPOSITORY_ID:'1434298007',
    DB:{prepare(sql) {return {bind(...args) {return {
      async first() {return settings.has(args[0])?{value:settings.get(args[0])}:null;},
      async run() {if(sql.startsWith('INSERT INTO settings')) settings.set(args[0],args[1]); if(sql.startsWith('INSERT INTO events')) events.push(args); return {meta:{changes:1}};},
      async all() {return {results:events};}
    };}};}}, settings, events};
}

test('China date rolls over eight hours ahead of UTC',()=>{
  assert.equal(chinaDate(Date.parse('2026-10-27T23:45:00Z')),'2026-10-28');
});
test('GitHub RSA private keys convert to a valid PKCS8 key',()=>{
  const {privateKey}=generateKeyPairSync('rsa',{modulusLength:2048});
  const pem=privateKey.export({type:'pkcs1',format:'pem'});
  const restored=createPrivateKey({key:Buffer.from(pkcs8(pem)),format:'der',type:'pkcs8'});
  assert.equal(restored.asymmetricKeyType,'rsa');
});
test('Public health never exposes credentials and admin access is required',async()=>{
  const env=environment();
  const health=await worker.fetch(new Request('https://test/health'),env);
  assert.deepEqual(await health.json(),{service:'news-digest-scheduler',configured:false});
  assert.equal((await worker.fetch(new Request('https://test/admin/status'),env)).status,404);
});
test('Setup manifest grants only Actions write and contents read',async()=>{
  const env=environment(); const setup=await setupToken(env.ADMIN_KEY);
  assert.notEqual(setup,env.ADMIN_KEY);
  const r=await worker.fetch(new Request('https://test/setup/'+setup),env);
  const body=await r.text();
  assert.ok(body.includes('&quot;actions&quot;:&quot;write&quot;'));
  assert.ok(body.includes('&quot;contents&quot;:&quot;read&quot;'));
  assert.ok(body.includes('&quot;public&quot;:false'));
  assert.ok(env.settings.has('manifest_state'));
});
test('Real scheduled handler records its event without sending when not armed',async()=>{
  const env=environment(); let pending;
  await worker.scheduled({cron:'* * * * *',scheduledTime:Date.now()},env,{waitUntil(p){pending=p;}});
  await pending;
  assert.equal(env.events[0][1],'cron_received');
  assert.equal(env.events.length,1);
});

test('Daily scheduler restricts token scope, skips an active run and retries a failed run',async()=>{
  const env=environment(); env.WORKFLOW='digest.yml';
  const {privateKey}=generateKeyPairSync('rsa',{modulusLength:2048});
  const app={id:123,pem:privateKey.export({type:'pkcs1',format:'pem'}),slug:'test'};
  const encoder=new TextEncoder(); const iv=crypto.getRandomValues(new Uint8Array(12));
  const key=await crypto.subtle.importKey('raw',await crypto.subtle.digest('SHA-256',encoder.encode(env.ADMIN_KEY)),'AES-GCM',false,['encrypt']);
  const cipher=await crypto.subtle.encrypt({name:'AES-GCM',iv},key,encoder.encode(JSON.stringify(app)));
  env.settings.set('app',JSON.stringify({iv:Buffer.from(iv).toString('base64'),data:Buffer.from(cipher).toString('base64')}));
  env.settings.set('installation',JSON.stringify({id:456}));
  const originalFetch=globalThis.fetch; let dispatches=0; let runStatus='in_progress';
  globalThis.fetch=async (url,options)=>{
    if(url.endsWith('/access_tokens')) {
      assert.deepEqual(JSON.parse(options.body),{repository_ids:[1434298007],permissions:{actions:'write',contents:'read'}});
      return Response.json({token:'test-only-token'});
    }
    if(url.includes('/runs?')) return Response.json({workflow_runs:[{created_at:new Date().toISOString(),display_title:'Daily digest · cloud-'+chinaDate(Date.now()),status:runStatus,conclusion:runStatus==='completed'?'failure':null}]});
    if(url.endsWith('/dispatches')) {
      dispatches++; const body=JSON.parse(options.body);
      assert.equal(body.inputs.delivery_time,'08:00');
      assert.equal(body.inputs.scheduler_test,false);
      return new Response(null,{status:204});
    }
    throw new Error('Unexpected URL in test');
  };
  async function tick() {let pending; await worker.scheduled({cron:'45,50,55 23 * * *',scheduledTime:Date.now()},env,{waitUntil(p){pending=p;}}); await pending;}
  try {
    await tick(); assert.equal(dispatches,1);
    await tick(); assert.equal(dispatches,1);
    runStatus='completed'; await tick(); assert.equal(dispatches,2);
  } finally {globalThis.fetch=originalFetch;}
});
