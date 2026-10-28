import {neon} from '@neondatabase/serverless';

export type RuntimeDemand = {
  pending: boolean;
  needs_attention: boolean;
  keep_alive: boolean;
  next_wake_at: number | null;
};
type Window = {start: number | null; end: number | null};
type Completion = {state: string; next_attempt_at: number | null};
type Inputs = {
  elections: Window[];
  verification_pending: boolean;
  verification_failed: boolean;
  emails: Completion[];
  completions: Completion[];
  missing_completion: boolean;
};

/** Dates are epoch milliseconds explicitly interpreted as UTC by PostgreSQL. */
export function demandFromRows(input: Inputs, now = Date.now()): RuntimeDemand {
  let keep = input.verification_pending || input.missing_completion;
  let attention = input.verification_failed;
  let wake: number | null = null;
  const schedule = (at: number) => { wake = wake === null ? at : Math.min(wake, at); };
  for (const election of input.elections) {
    if (election.end !== null && election.end <= now) continue;
    const start = election.start ?? now;
    if (start <= now + 5 * 60_000) keep = true;
    else schedule(start - 5 * 60_000);
  }
  for (const job of [...input.emails, ...input.completions]) {
    if (['failed', 'blocked'].includes(job.state)) { attention = true; continue; }
    if (['sending', 'working'].includes(job.state)) keep = true;
    else if (job.state === 'pending') {
      if (job.next_attempt_at === null || job.next_attempt_at <= now) keep = true;
      else schedule(job.next_attempt_at);
    }
  }
  return {pending: input.verification_pending, needs_attention: attention, keep_alive: keep, next_wake_at: wake};
}

/** Read aggregate lifecycle metadata over HTTPS without starting a container. */
export async function runtimeDemand(env: Pick<Env, 'DATABASE_URL' | 'ALU_BRIDGE_CLIENT_ID' | 'ALU_BRIDGE_ELECTIONS'>): Promise<RuntimeDemand> {
  const sql = neon(env.DATABASE_URL, {fetchOptions: {signal: AbortSignal.timeout(10_000)}});
  const client = env.ALU_BRIDGE_CLIENT_ID;
  const allowed = env.ALU_BRIDGE_ELECTIONS.split(',').map(s => s.trim()).filter(Boolean);
  const [windows, queues, metadata, emails] = await sql.transaction([
    sql.query(`select extract(epoch from coalesce(e.voting_started_at,e.voting_starts_at,e.frozen_at) at time zone 'UTC') * 1000 as start,
      extract(epoch from coalesce(e.voting_extended_until,e.voting_ends_at) at time zone 'UTC') * 1000 as "end"
      from helios_election e where e.deleted_at is null and e.frozen_at is not null
      and e.voting_ended_at is null and e.tallying_started_at is null and e.result_released_at is null
      and (exists(select 1 from helios_aluelectionbinding b where b.election_id=e.id and b.client_id=$1) or e.uuid=any($2::varchar[]))
      limit 1001`, [client, allowed]),
    sql.query(`select exists(select 1 from helios_voteverificationjob j
      join helios_castvote c on c.id=j.cast_vote_id join helios_voter v on v.id=c.voter_id
      join helios_election e on e.id=v.election_id where j.state='pending' and e.deleted_at is null
      and (c.quarantined_p=false or c.released_from_quarantine_at is not null)) as pending,
      exists(select 1 from helios_voteverificationjob j join helios_castvote c on c.id=j.cast_vote_id
      join helios_voter v on v.id=c.voter_id join helios_election e on e.id=v.election_id
      where j.state='failed' and e.deleted_at is null) as failed`),
    sql.query("select to_regclass('public.helios_electioncompletionjob') is not null as available"),
    sql.query(`select state, extract(epoch from min(next_attempt_at) at time zone 'UTC') * 1000 as next_attempt_at
      from helios_voteconfirmationemail where state in ('pending','sending') group by state`),
  ], {readOnly: true, isolationLevel: 'RepeatableRead'});
  let completions: Record<string, unknown>[] = [];
  let missing = false;
  // The restored older image has not applied the completion migration yet.
  // Its absence must never create an endless paid recovery loop.
  if (metadata[0]?.available === true) {
    const [jobs, unqueued] = await sql.transaction([
      sql.query(`select j.state,extract(epoch from min(j.next_attempt_at) at time zone 'UTC') * 1000 as next_attempt_at
        from helios_electioncompletionjob j join helios_election e on e.id=j.election_id
        where e.deleted_at is null and e.result_released_at is null and j.state in ('pending','working','blocked','failed') group by j.state`),
      sql.query(`select exists(select 1 from helios_election e where e.deleted_at is null and e.private_p=false
        and e.frozen_at is not null and e.result_released_at is null
        and (e.tallying_started_at is not null or e.voting_ended_at <= current_timestamp at time zone 'UTC'
          or (e.voting_ended_at is null and coalesce(e.voting_extended_until,e.voting_ends_at) <= current_timestamp at time zone 'UTC'))
        and (exists(select 1 from helios_aluelectionbinding b where b.election_id=e.id and b.client_id=$1) or e.uuid=any($2::varchar[]))
        and not exists(select 1 from helios_electioncompletionjob j where j.election_id=e.id)) as missing`, [client, allowed]),
    ], {readOnly: true, isolationLevel: 'RepeatableRead'});
    completions = jobs;
    if (typeof unqueued[0]?.missing !== 'boolean') throw new Error('Invalid completion metadata.');
    missing = unqueued[0].missing;
  }
  if (windows.length > 1000 || emails.length > 1000 || completions.length > 1000 ||
      typeof queues[0]?.pending !== 'boolean' || typeof queues[0]?.failed !== 'boolean' ||
      typeof metadata[0]?.available !== 'boolean') {
    throw new Error('Runtime demand metadata unavailable.');
  }
  const epoch = (value: unknown): number | null => {
    if (value === null) return null;
    const result = Number(value);
    if (!Number.isFinite(result) || result <= 0) throw new Error('Invalid runtime schedule.');
    return result;
  };
  return demandFromRows({
    elections: windows.map(w => ({start: epoch(w.start), end: epoch(w.end)})),
    verification_pending: queues[0].pending, verification_failed: queues[0].failed,
    emails: emails.map(j => ({state: String(j.state), next_attempt_at: epoch(j.next_attempt_at)})),
    completions: completions.map(j => ({state: String(j.state), next_attempt_at: epoch(j.next_attempt_at)})),
    missing_completion: missing,
  });
}
