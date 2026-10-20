import assert from 'node:assert/strict';
import { test } from 'node:test';
import { verifyPlacement } from './check-placement.mjs';
const headers={'x-voting-location':'bos03','x-voting-region':'ENAM','x-voting-database-region':'us-east-2','x-voting-database-pooler':'direct'};
function provider(states) {
  return (command)=>command==='list'?[{id:'test',name:'alu-voting-backend-votingbackend'}]:
    command==='info'?{constraints:{regions:['ENAM']}}:[{state:states.shift()||'running',location:'bos03'}];
}
test('waits for old-image headers and departing instances before certifying a rollout',async()=>{
  let probes=0,waits=0;
  const result=await verifyPlacement({run:provider(['running','inactive','running']),
    fetcher:async()=>new Response('',{status:404,headers:++probes===1?{}:headers}),
    wait:async()=>{waits++;}});
  assert.equal(probes,3);assert.equal(waits,2);
  assert.equal(result.database_region,'us-east-2');assert.equal(result.instances[0].location,'bos03');
});
test('never certifies mismatched database placement or a transaction pooler',async()=>{
  for (const bad of [{'x-voting-database-region':'eu-west-1'},{'x-voting-database-pooler':'transaction'},{'x-voting-region':'AFR'}]) {
    await assert.rejects(verifyPlacement({run:provider(['running']),attempts:2,
      fetcher:async()=>new Response('',{status:404,headers:{...headers,...bad}}),wait:async()=>{}}),/did not converge/);
  }
});
