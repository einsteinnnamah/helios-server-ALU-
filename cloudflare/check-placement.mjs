// Read-only post-deploy verification. Raw provider configuration may contain
// secrets; return only sanitized placement fields. A rollout can briefly serve
// an old image or list its departing instance as inactive. Wait for convergence.
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

function wrangler(...args) {
  try {
    return JSON.parse(execFileSync(process.execPath,
      ['node_modules/wrangler/bin/wrangler.js', 'containers', ...args, '--json'],
      { encoding: 'utf8', timeout: 60_000, stdio: ['ignore', 'pipe', 'pipe'] }));
  } catch {
    throw new Error('Container metadata unavailable; provider output withheld.');
  }
}

export async function verifyPlacement({run=wrangler,fetcher=fetch,
  wait=ms=>new Promise(resolve=>setTimeout(resolve,ms)),attempts=12}={}) {
  const applications = run('list');
  const application = applications.find(a=>a.name==='alu-voting-backend-votingbackend');
  if (!application) throw new Error('Voting backend application was not found.');
  const info = run('info',application.id);
  const constraints = info.constraints?.regions ?? [];
  if (constraints.length!==1 || constraints[0]!=='ENAM') throw new Error('Expected ENAM placement constraints.');
  for (let attempt=0;attempt<attempts;attempt++) {
    try {
      // Unknown-election GET: no voter, grant, real ballot or mutation.
      const probe=await fetcher('https://alu-voting-backend.e-nnamah.workers.dev/helios/elections/00000000-0000-4000-8000-000000000000/ui/ballot',{
        redirect:'error',cache:'no-store',signal:AbortSignal.timeout(60_000),
      });
      await probe.body?.cancel();
      const diagnostic={
        container_location:probe.headers.get('x-voting-location'),
        container_region:probe.headers.get('x-voting-region'),
        database_region:probe.headers.get('x-voting-database-region'),
        database_pooler:probe.headers.get('x-voting-database-pooler'),
      };
      const instances=run('instances',application.id);
      const rows=Array.isArray(instances)?instances:instances.instances;
      if (!Array.isArray(rows)) throw new Error('Unknown instance response.');
      const active=rows.filter(i=>i.location && i.state==='running');
      if (probe.status===404 && active.length && diagnostic.database_region==='us-east-2' &&
          diagnostic.database_pooler==='direct' && diagnostic.container_region?.toUpperCase()==='ENAM' &&
          diagnostic.container_location && diagnostic.container_location!=='unknown') {
        return {constraints,...diagnostic,instances:active.map(i=>({state:i.state,
          location:typeof i.location==='string'?i.location:i.location?.name,region:i.location?.region}))};
      }
    } catch {
      // Provider/HTTP details can include credentials; retry without logging.
    }
    if (attempt+1<attempts) await wait(5000);
  }
  throw new Error('Container placement did not converge to the direct Ohio database configuration.');
}
if (process.argv[1] && pathToFileURL(process.argv[1]).href===import.meta.url) {
  console.log(JSON.stringify(await verifyPlacement(),null,2));
}
