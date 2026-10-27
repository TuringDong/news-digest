const enc = new TextEncoder();
const dec = new TextDecoder();
const b64 = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes)));
const unb64 = text => Uint8Array.from(atob(text), c => c.charCodeAt(0));
const b64url = bytes => b64(bytes).replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');
const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const chinaDate = ms => new Date(ms + 8 * 3600_000).toISOString().slice(0, 10);
export const setupToken = async key => b64url(await crypto.subtle.digest('SHA-256',enc.encode('setup:'+key)));
const json = (data, status = 200) => new Response(JSON.stringify(data), {status, headers: {'content-type':'application/json; charset=utf-8','cache-control':'no-store'}});
const html = body => new Response(`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>日报云端调度</title><style>body{font:17px/1.7 system-ui;background:#eef3fb;color:#20324d;max-width:760px;margin:60px auto;padding:28px}main{background:white;padding:32px;border-radius:18px}button,a.button{background:#2469d8;color:white;padding:12px 20px;border:0;border-radius:10px;font-size:17px;text-decoration:none}code{background:#282c34;color:#abb2bf;padding:4px 8px}small{color:#58697f}</style><main>${body}</main>`, {headers:{'content-type':'text/html; charset=utf-8','cache-control':'no-store','referrer-policy':'no-referrer','x-content-type-options':'nosniff'}});

async function get(env, key) { const r = await env.DB.prepare('SELECT value FROM settings WHERE key=?').bind(key).first(); return r ? JSON.parse(r.value) : null; }
async function put(env, key, value) { await env.DB.prepare('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value').bind(key, JSON.stringify(value)).run(); }
async function event(env, kind, detail) { console.log(JSON.stringify({kind, ...detail})); await env.DB.prepare('INSERT INTO events(at,kind,detail) VALUES(?,?,?)').bind(new Date().toISOString(),kind,JSON.stringify(detail)).run(); }
async function lock(env, key) { const now = Date.now(); const r = await env.DB.prepare('INSERT INTO locks(key,expires) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET expires=excluded.expires WHERE locks.expires < ?').bind(key,now+120000,now).run(); return r.meta.changes === 1; }
async function unlock(env, key) { await env.DB.prepare('DELETE FROM locks WHERE key=?').bind(key).run(); }
async function aesKey(env) { return crypto.subtle.importKey('raw', await crypto.subtle.digest('SHA-256',enc.encode(env.ADMIN_KEY)), 'AES-GCM', false, ['encrypt','decrypt']); }
async function seal(env, value) { const iv=crypto.getRandomValues(new Uint8Array(12)); const data=await crypto.subtle.encrypt({name:'AES-GCM',iv},await aesKey(env),enc.encode(JSON.stringify(value))); return {iv:b64(iv),data:b64(data)}; }
async function unseal(env, value) { return JSON.parse(dec.decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:unb64(value.iv)},await aesKey(env),unb64(value.data)))); }
function der(tag, data) { const a=new Uint8Array(data); let n=a.length; const l=[]; do {l.unshift(n&255); n>>=8;} while(n); return Uint8Array.from([tag,...(a.length<128?[a.length]:[128|l.length,...l]),...a]); }
export function pkcs8(pem) { const key=unb64(pem.replace(/-----(?:BEGIN|END) [^-]+-----/g,'').replace(/\s/g,'')); if(pem.includes('BEGIN PRIVATE KEY')) return key; return der(0x30, Uint8Array.from([2,1,0,0x30,0x0d,6,9,0x2a,0x86,0x48,0x86,0xf7,0x0d,1,1,1,5,0,...der(4,key)])); }
async function appJwt(app) { const now=Math.floor(Date.now()/1000); const unsigned=b64url(enc.encode(JSON.stringify({alg:'RS256',typ:'JWT'})))+'.'+b64url(enc.encode(JSON.stringify({iat:now-60,exp:now+540,iss:String(app.id)}))); const key=await crypto.subtle.importKey('pkcs8',pkcs8(app.pem),{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['sign']); return unsigned+'.'+b64url(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',key,enc.encode(unsigned))); }
async function gh(path, token, method='GET', body) { const r=await fetch('https://api.github.com'+path,{method,headers:{Accept:'application/vnd.github+json','User-Agent':'news-digest-cloud-scheduler','X-GitHub-Api-Version':'2022-11-28',...(token?{Authorization:'Bearer '+token}:{}),...(body?{'content-type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})}); if(!r.ok) throw new Error(`GitHub ${r.status} ${method} ${path.split('?')[0].replace(/app-manifests\/[^/]+/, 'app-manifests/[redacted]')}`); return r.status===204?null:r.json(); }
async function appConfig(env) { const encrypted=await get(env,'app'); return encrypted?unseal(env,encrypted):null; }
async function installToken(env, app, installation) { return (await gh(`/app/installations/${installation}/access_tokens`,await appJwt(app),'POST',{repository_ids:[Number(env.REPOSITORY_ID)],permissions:{actions:'write',contents:'read'}})).token; }
async function dispatch(env, inputs, kind) {
  const app=await appConfig(env); const install=await get(env,'installation');
  if(!app || !install) return {status:'awaiting_github_installation'};
  const token=await installToken(env,app,install.id);
  await gh(`/repos/${env.REPOSITORY}/actions/workflows/${env.WORKFLOW}/dispatches`,token,'POST',{ref:'main',inputs});
  await event(env,kind,{delivery_time:inputs.delivery_time,repository:env.REPOSITORY});
  return {status:'dispatched'};
}

async function daily(env) {
  const date=chinaDate(Date.now()); const key='delivery:'+date;
  if(!await lock(env,key)) return {status:'busy'};
  try {
    const app=await appConfig(env); const install=await get(env,'installation');
    if(!app || !install) return {status:'awaiting_github_installation'};
    const token=await installToken(env,app,install.id);
    const previous=await get(env,key);
    if(previous) {
      const runs=await gh(`/repos/${env.REPOSITORY}/actions/workflows/${env.WORKFLOW}/runs?event=workflow_dispatch&per_page=20`,token);
      const relevant=runs.workflow_runs.filter(r=>Date.parse(r.created_at)>=previous.at-5000 && r.display_title===`Daily digest · cloud-${date}`);
      if(relevant.some(r=>r.status!=='completed'||r.conclusion==='success')) return {status:'already_running_or_complete'};
      if(!relevant.length && Date.now()-previous.at<8*60000) return {status:'awaiting_run_registration'};
    }
    await gh(`/repos/${env.REPOSITORY}/actions/workflows/${env.WORKFLOW}/dispatches`,token,'POST',{ref:'main',inputs:{dry_run:false,delivery_time:'08:00',scheduler_test:false,dispatch_label:'cloud-'+date}});
    await put(env,key,{at:Date.now()}); await event(env,'daily_dispatched',{date,delivery_time:'08:00'});
    return {status:'dispatched'};
  } finally { await unlock(env,key); }
}

async function scheduled(controller,env) {
  await event(env,'cron_received',{cron:controller.cron,scheduled_time:new Date(controller.scheduledTime).toISOString()});
  if(controller.cron==='* * * * *') {
    const probe=await get(env,'probe');
    if(probe && !probe.dispatched && Date.now()>=probe.after && Date.now()<=probe.expires && await lock(env,'probe')) {
      try {
        const fresh=await get(env,'probe');
        if(!fresh.dispatched) {
          const result=await dispatch(env,{dry_run:false,delivery_time:fresh.delivery_time,scheduler_test:true,dispatch_label:'cloud-test-'+fresh.id},'probe_dispatched');
          if(result.status==='dispatched') await put(env,'probe',{...fresh,dispatched:true,at:Date.now()});
        }
      } finally { await unlock(env,'probe'); }
    }
  } else { const result=await daily(env); await event(env,'daily_result',result); }
}

async function fetchHandler(request,env) {
  const u=new URL(request.url); const app=await appConfig(env);
  if(u.pathname==='/health') return json({service:'news-digest-scheduler',configured:Boolean(app&&await get(env,'installation'))});
  if(u.pathname==='/setup/callback') {
    const pending=await get(env,'manifest_state');
    if(app || !pending || pending.state!==u.searchParams.get('state') || pending.expires<Date.now()) return html('<h1>安装会话无效或已完成</h1><p>请返回原安装入口。</p>');
    const code=u.searchParams.get('code'); if(!code||!/^[a-zA-Z0-9_-]+$/.test(code)) return json({error:'invalid_code'},400);
    const result=await gh(`/app-manifests/${code}/conversions`,null,'POST');
    if(result.owner?.login!=='TuringDong') return json({error:'wrong_app_owner'},403);
    await put(env,'app',await seal(env,{id:result.id,pem:result.pem,slug:result.slug}));
    await put(env,'manifest_state',null);
    await event(env,'app_registered',{id:result.id,slug:result.slug});
    return html(`<h1>应用已创建</h1><p>最后一步：安装到 <strong>TuringDong/news-digest</strong>，仅选择这个仓库。</p><a class="button" href="${escape(result.html_url)}/installations/new">选择仓库并安装</a><p><small>权限：Actions 读写、仓库内容只读；不会获得代码写入权限。</small></p>`);
  }
  if(u.pathname==='/setup/installed') {
    const id=u.searchParams.get('installation_id');
    if(!app||!/^\d+$/.test(id||'')) return json({error:'invalid_installation'},400);
    const info=await gh('/app/installations/'+id,await appJwt(app));
    if(info.account?.login!=='TuringDong'||info.repository_selection!=='selected') return html('<h1>请选择单个仓库</h1><p>请回到 GitHub 安装设置，选择 Only select repositories，并仅授权 news-digest。</p>');
    const token=await installToken(env,app,id);
    const repo=await gh('/repos/'+env.REPOSITORY,token);
    if(repo.id!==Number(env.REPOSITORY_ID)) return json({error:'wrong_repository'},403);
    await put(env,'installation',{id:Number(id)}); await event(env,'app_installed',{repository:env.REPOSITORY});
    return html('<h1>云端调度连接成功</h1><p>现在可以返回聊天，我会继续完成自动触发和定时邮件验收。</p><p>你的电脑关机或关闭 VPN，不会影响 Cloudflare 和 GitHub 的云端运行。</p>');
  }
  const setupKey=u.pathname.startsWith('/setup/')?u.pathname.slice(7):'';
  const authorized=Boolean(env.ADMIN_KEY) && (request.headers.get('Authorization')==='Bearer '+env.ADMIN_KEY || setupKey===await setupToken(env.ADMIN_KEY));
  if(!authorized) return json({error:'not_found'},404);
  if(u.pathname.startsWith('/setup/')) {
    if(app) return html(`<h1>应用已创建</h1><p>请仅安装到 news-digest 仓库。</p><a class="button" href="https://github.com/apps/${escape(app.slug)}/installations/new">继续安装</a>`);
    const state=b64url(crypto.getRandomValues(new Uint8Array(24))); await put(env,'manifest_state',{state,expires:Date.now()+3600000});
    const manifest={name:'News Digest TuringDong 20261027',url:'https://github.com/'+env.REPOSITORY,description:'Cloudflare 定时唤醒日报工作流。仅需所选 news-digest 仓库的 Actions 读写和内容只读权限。',public:false,redirect_url:u.origin+'/setup/callback',setup_url:u.origin+'/setup/installed',hook_attributes:{url:u.origin+'/webhook',active:false},default_permissions:{actions:'write',contents:'read'},default_events:[]};
    return html(`<h1>连接你的 GitHub 日报仓库</h1><p>Cloudflare 每天提前唤醒现有 Python 工作流，准备完成后等到北京时间 <strong>08:00</strong> 发信。</p><p>下一页会创建一个属于你的私有 GitHub App。随后请选择 <strong>Only select repositories → news-digest</strong>。</p><ul><li>Actions：读写，用于启动和检查运行。</li><li>Contents：只读，用于读取状态；不能修改代码。</li><li>安装令牌自动刷新，无需定期更换个人访问令牌。</li></ul><form action="https://github.com/settings/apps/new?state=${state}" method="post"><input type="hidden" name="manifest" value="${escape(JSON.stringify(manifest))}"><button>前往 GitHub 确认创建应用</button></form><p><small>只有你在 GitHub 上确认创建和安装后，这项授权才会生效。</small></p>`);
  }
  if(u.pathname==='/admin/status') {
    const events=await env.DB.prepare('SELECT at,kind,detail FROM events ORDER BY id DESC LIMIT 30').all();
    return json({configured:Boolean(app&&await get(env,'installation')),app:app?{id:app.id,slug:app.slug}:null,installation:await get(env,'installation'),probe:await get(env,'probe'),events:events.results});
  }
  if(u.pathname==='/admin/probe'&&request.method==='POST') {
    const body=await request.json();
    if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(body.delivery_time)) return json({error:'invalid_delivery_time'},400);
    const now=Date.now();
    const after=body.not_before ? Date.parse(body.not_before) : now;
    if(!Number.isFinite(after)||after<now-60000||after>now+15*60000) return json({error:'invalid_not_before'},400);
    const probe={id:crypto.randomUUID(),delivery_time:body.delivery_time,after,expires:now+15*60000,dispatched:false}; await put(env,'probe',probe); return json(probe);
  }
  return json({error:'not_found'},404);
}

export default {
  async fetch(request,env) { try {return await fetchHandler(request,env);} catch(e) {console.error(e.message);return json({error:'operation_failed',detail:e.message},500);} },
  async scheduled(controller,env,ctx) {ctx.waitUntil(scheduled(controller,env).catch(async e=>{await event(env,'scheduler_error',{error:e.message});throw e;}));}
};
