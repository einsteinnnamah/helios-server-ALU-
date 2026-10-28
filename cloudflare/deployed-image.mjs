import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const prefix='registry.cloudflare.com/c66816623540ac2342c071dee2a16704/alu-voting-backend-votingbackend@';
export function deployedImage(log) {
  const references=[...log.matchAll(/registry\.cloudflare\.com\/c66816623540ac2342c071dee2a16704\/alu-voting-backend-votingbackend@(sha256:[a-f0-9]{64})/g)];
  const digest=references.at(-1)?.[1]??[...log.matchAll(/\bdigest:\s*(sha256:[a-f0-9]{64})\b/g)].at(-1)?.[1];
  if(!digest)throw new Error('The deployed container digest was not recorded; refusing to certify an unknown image.');
  return prefix+digest;
}
if(process.argv[1]&&pathToFileURL(process.argv[1]).href===import.meta.url){
  console.log('EXPECTED_CONTAINER_IMAGE='+deployedImage(await readFile(process.argv[2],'utf8')));
}
