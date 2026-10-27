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
