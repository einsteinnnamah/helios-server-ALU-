import assert from 'node:assert/strict';
import {test, before, after} from 'node:test';
import {DatabaseSync} from 'node:sqlite';
import {timingSafeEqual} from 'node:crypto';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {build} from 'esbuild';

let worker,VerificationRecovery,temporary;
const realNow=Date.now;
let now=Date.UTC(2026,9,27,12);
const secureCompare=crypto.subtle.timingSafeEqual;
const stores=[];
before(async()=>{
  Date.now=()=>now;
  if(!secureCompare)crypto.subtle.timingSafeEqual=timingSafeEqual;
  temporary=await mkdtemp(join(tmpdir(),'alu-lifecycle-'));
  const outfile=join(temporary,'worker.mjs');
  await build({entryPoints:[fileURLToPath(new URL('./index.ts',import.meta.url))],outfile,
    bundle:true,platform:'node',format:'esm',logLevel:'silent',plugins:[{name:'platform-boundaries',setup(b){
      b.onResolve({filter:/^(cloudflare:workers|@cloudflare\/containers)$/},a=>({path:a.path,namespace:'fixture'}));
      b.onLoad({filter:/.*/,namespace:'fixture'},a=>({contents:`export class ${a.path==='cloudflare:workers'?'DurableObject':'Container'} { constructor(ctx,env){this.ctx=ctx;this.env=env;} }`}));
    }}]});
  ({default:worker,VerificationRecovery}=await import(pathToFileURL(outfile)));
});
after(async()=>{
  Date.now=realNow;
  if(!secureCompare)delete crypto.subtle.timingSafeEqual;
  for(const db of stores)db.close();
  await rm(temporary,{recursive:true,force:true});
});
const idle={pending:false,needs_attention:false,keep_alive:false,next_wake_at:null};
function recovery(probe=async()=>Response.json(idle)){
  const db=new DatabaseSync(':memory:');stores.push(db);
  const storage={alarmAt:null,sql:{exec(sql,...args){
    const statement=db.prepare(sql);
    if(!/^SELECT/i.test(sql)){statement.run(...args);return {};}
    const rows=statement.all(...args);return {one(){assert.equal(rows.length,1);return rows[0];}};
  }},async getAlarm(){return this.alarmAt;},async setAlarm(t){this.alarmAt=t;},async deleteAlarm(){this.alarmAt=null;}};
  const env={PUBLIC_BACKEND_ORIGIN:'https://backend.example',RECOVERY_SECRET:'test-only',
    BACKEND:{getByName:()=>({fetch:probe})}};
  return {object:new VerificationRecovery({storage},env),storage};
}

test('an empty queue stops polling, while a future opening has one scheduled wake',async()=>{
  const r=recovery();await r.object.alarm();assert.equal(r.storage.alarmAt,null);
  const future=now+24*60*60_000;
  const s=recovery(async()=>Response.json({...idle,next_wake_at:future}));
  await s.object.alarm();assert.equal(s.storage.alarmAt,future);
});
test('runnable work or a bounded prewarm window retains the recovery alarm',async()=>{
  for(const state of [{...idle,pending:true},{...idle,keep_alive:true}]){
    const r=recovery(async()=>Response.json(state));await r.object.alarm();assert.equal(r.storage.alarmAt,now+60_000);
  }
});
test('an active durable request lease prevents premature idle, then expires',async()=>{
  const r=recovery();const lease=await r.object.arm();await r.object.alarm();
  assert.equal(r.storage.alarmAt,now+60_000);
  await r.object.finish(lease);await r.object.alarm();assert.equal(r.storage.alarmAt,null);
  await r.object.arm();now+=10*60_000+1;await r.object.alarm();assert.equal(r.storage.alarmAt,null);
});
test('a request arriving during an empty probe cannot lose its recovery alarm',async()=>{
  let release;const held=new Promise(resolve=>{release=resolve;});
  const r=recovery(()=>held);const alarm=r.object.alarm();await Promise.resolve();
  await r.object.arm();release(Response.json(idle));await alarm;
  assert.equal(r.storage.alarmAt,now+60_000);
});
test('failed or malformed probes keep a durable retry scheduled',async()=>{
  for(const response of [new Response(null,{status:503}),Response.json({pending:false})]){
    const r=recovery(async()=>response);await assert.rejects(r.object.alarm());
    assert.equal(r.storage.alarmAt,now+60_000);
  }
});
test('JSON submission arms recovery before forwarding and finishes its lease',async()=>{
  const events=[];
  const env={PUBLIC_BACKEND_ORIGIN:'https://backend.example',ALU_BRIDGE_SECRET:'test-secret-only',
    ALU_BRIDGE_APP_ORIGIN:'https://app.example',VOTE_REQUESTS:{limit:async()=>({success:true})},
    RECOVERY:{getByName:()=>({arm:async()=>{events.push('arm');return 'lease';},finish:async id=>{assert.equal(id,'lease');events.push('finish');}})},
    BACKEND:{getByName:()=>({fetch:async()=>{events.push('forward');return Response.json({status:'pending'});}})}};
  const request=(auth=true)=>new Request('https://backend.example/helios/elections/test/ui/cast',{
    method:'POST',headers:{'content-type':'application/json',...(auth?{authorization:'Bearer '+env.ALU_BRIDGE_SECRET}:{})},body:'{}'});
  assert.equal((await worker.fetch(request(),env)).status,200);assert.deepEqual(events,['arm','forward','finish']);
  events.length=0;assert.equal((await worker.fetch(request(false),env)).status,401);assert.deepEqual(events,[]);
  env.BACKEND.getByName=()=>({fetch:async()=>{events.push('forward');throw Error('Lost response after commit');}});
  assert.equal((await worker.fetch(request(),env)).status,503);assert.deepEqual(events,['arm','forward','finish']);
});
