import assert from 'node:assert/strict';
import {test,before,after} from 'node:test';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {build} from 'esbuild';
let demand,temporary;
before(async()=>{
  temporary=await mkdtemp(join(tmpdir(),'alu-demand-'));
  const outfile=join(temporary,'demand.mjs');
  await build({entryPoints:[fileURLToPath(new URL('./demand.ts',import.meta.url))],outfile,bundle:true,platform:'node',format:'esm',logLevel:'silent'});
  demand=(await import(pathToFileURL(outfile))).demandFromRows;
});
after(async()=>{await rm(temporary,{recursive:true,force:true});});
const now=Date.UTC(2026,9,28,12);
const empty=()=>({elections:[],verification_pending:false,verification_failed:false,emails:[],completions:[],missing_completion:false});
test('no election or work has no paid keepalive and no alarm',()=>{
  assert.deepEqual(demand(empty(),now),{pending:false,needs_attention:false,keep_alive:false,next_wake_at:null});
});
test('scheduled voting wakes exactly five minutes before opening',()=>{
  const input={...empty(),elections:[{start:now+60*60_000,end:now+120*60_000}]};
  assert.equal(demand(input,now).next_wake_at,now+55*60_000);
  assert.equal(demand(input,now+55*60_000-1).keep_alive,false);
  assert.equal(demand(input,now+55*60_000).keep_alive,true);
});
test('open voting stays warm even without voters or requests',()=>{
  assert.equal(demand({...empty(),elections:[{start:now-60_000,end:now+60_000}]},now).keep_alive,true);
});
test('scheduled closure stops pinning uptime at its deadline',()=>{
  const input={...empty(),elections:[{start:now-60_000,end:now}]};
  assert.equal(demand(input,now-1).keep_alive,true);
  assert.equal(demand(input,now).keep_alive,false);
});
test('closing one election leaves another open election warm',()=>{
  const input={...empty(),elections:[{start:now-60_000,end:now},{start:now-60_000,end:now+60_000}]};
  assert.equal(demand(input,now).keep_alive,true);
});
test('verification and runnable count/archive work finish after closure',()=>{
  assert.equal(demand({...empty(),verification_pending:true},now).keep_alive,true);
  assert.equal(demand({...empty(),missing_completion:true},now).keep_alive,true);
  for(const state of ['pending','working'])assert.equal(demand({...empty(),completions:[{state,next_attempt_at:now}]},now).keep_alive,true);
  assert.equal(demand({...empty(),completions:[{state:'saved',next_attempt_at:now}]},now).keep_alive,false);
});
test('future email and completion retries sleep until work is due',()=>{
  const input={...empty(),emails:[{state:'pending',next_attempt_at:now+120_000}],completions:[{state:'pending',next_attempt_at:now+60_000}]};
  assert.equal(demand(input,now).keep_alive,false);
  assert.equal(demand(input,now).next_wake_at,now+60_000);
  assert.equal(demand(input,now+60_000).keep_alive,true);
});
test('failed or blocked jobs request attention without endless paid uptime',()=>{
  const state=demand({...empty(),verification_failed:true,completions:[{state:'blocked',next_attempt_at:now}]},now);
  assert.equal(state.needs_attention,true);assert.equal(state.keep_alive,false);assert.equal(state.next_wake_at,null);
});
