import assert from 'node:assert/strict';
import { test } from 'node:test';
import { verifyPlacement } from './check-placement.mjs';
import {deployedImage} from './deployed-image.mjs';
const headers={'x-voting-location':'bos03','x-voting-region':'ENAM','x-voting-database-region':'us-east-2','x-voting-database-pooler':'direct','x-voting-automatic-completion':'enabled'};
function provider(states) {
  return (command)=>command==='list'?[{id:'test',name:'alu-voting-backend-votingbackend'}]:
    command==='info'?{constraints:{regions:['ENAM']},version:19}:[{state:states.shift()||'running',location:'bos03',version:19}];
}
test('waits for old-image headers and departing instances before certifying a rollout',async()=>{
  let probes=0,waits=0;
  const result=await verifyPlacement({run:provider(['running','inactive','running']),
    fetcher:async()=>new Response('',{status:404,headers:++probes===1?{}:headers}),
    wait:async()=>{waits++;}});
  assert.equal(probes,3);assert.equal(waits,2);
  assert.equal(result.database_region,'us-east-2');assert.equal(result.instances[0].location,'bos03');
});
test('a healthy old image cannot certify the intended release',async()=>{
  let infoCalls=0;
  const run=command=>command==='list'?[{id:'test',name:'alu-voting-backend-votingbackend'}]:command==='info'?
    {constraints:{regions:['ENAM']},version:infoCalls++<2?18:19,configuration:{image:infoCalls<=2?'old':'new'}}:
    [{state:'running',location:'bos03',version:infoCalls<=2?18:19}];
  let probes=0;
  const result=await verifyPlacement({run,expectedImage:'new',fetcher:async()=>{probes++;return new Response('',{status:404,headers});},wait:async()=>{}});
  assert.equal(probes,2);assert.equal(result.version,19);assert.equal(result.image,'new');
});
test('missing completion support and stale instance versions cannot pass',async()=>{
  for(const [completion,version] of [[undefined,19],['disabled',19],['enabled',18]]){
    const h={...headers};if(completion===undefined)delete h['x-voting-automatic-completion'];else h['x-voting-automatic-completion']=completion;
    await assert.rejects(verifyPlacement({attempts:2,run:cmd=>cmd==='list'?[{id:'test',name:'alu-voting-backend-votingbackend'}]:cmd==='info'?{constraints:{regions:['ENAM']},version:19}:[{state:'running',location:'bos03',version}],fetcher:async()=>new Response('',{status:404,headers:h}),wait:async()=>{}}),/did not converge/);
  }
});
test('deployment output binds verification to the final owned image digest',()=>{
  const prefix='registry.cloudflare.com/c66816623540ac2342c071dee2a16704/alu-voting-backend-votingbackend@';
  assert.equal(deployedImage('old '+prefix+'sha256:'+'a'.repeat(64)+'\nnew '+prefix+'sha256:'+'b'.repeat(64)),prefix+'sha256:'+'b'.repeat(64));
  assert.equal(deployedImage('release: digest: sha256:'+'c'.repeat(64)+' size: 2668'),prefix+'sha256:'+'c'.repeat(64));
  assert.throws(()=>deployedImage('Uploaded Worker successfully'),/refusing to certify/);
});
test('never certifies mismatched database placement or a transaction pooler',async()=>{
  for (const bad of [{'x-voting-database-region':'eu-west-1'},{'x-voting-database-pooler':'transaction'},{'x-voting-region':'AFR'}]) {
    await assert.rejects(verifyPlacement({run:provider(['running']),attempts:2,
      fetcher:async()=>new Response('',{status:404,headers:{...headers,...bad}}),wait:async()=>{}}),/did not converge/);
  }
});
