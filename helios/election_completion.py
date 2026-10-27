"""Automatically count closed ALU elections and durably deliver a private archive.

Public release remains an explicit committee action. No keys, identities of
voters, individual ballots, or decrypted individual choices enter the archive.
"""
import datetime
import uuid
import requests
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from .models import Election, ElectionCompletionJob, AluElectionBinding, VoteVerificationJob
from .bridge_eligibility import require_policy_decisions
from .alu_report import operational_report
from .crypto import algs
from helios_auth.bridge_protocol import https_origin


class CompletionBlocked(Exception):
    pass


def enabled():
    return getattr(settings, 'ALU_AUTOMATIC_COMPLETION', False)


def closed_elections(now):
    bound = Q(aluelectionbinding__client_id=settings.ALU_BRIDGE_CLIENT_ID)
    bound |= Q(uuid__in=settings.ALU_BRIDGE_ELECTIONS)
    closed = (Q(tallying_started_at__isnull=False) | Q(voting_ended_at__lte=now) |
        Q(voting_ended_at__isnull=True, voting_extended_until__lte=now) |
        Q(voting_ended_at__isnull=True, voting_extended_until__isnull=True, voting_ends_at__lte=now))
    return Election.objects.filter(bound, closed, frozen_at__isnull=False, private_p=False,
        result_released_at__isnull=True)


def recovery_schedule(now):
    """Read-only lifecycle input, including retries after a container restart."""
    if not enabled():
        return False, None, False
    elections = closed_elections(now)
    missing = elections.filter(completion_job__isnull=True).exists()
    jobs = ElectionCompletionJob.objects.filter(election__in=elections)
    due = jobs.filter(Q(state='pending', next_attempt_at__lte=now) |
        Q(state='working', lease_until__lte=now)).exists()
    working = jobs.filter(state='working', lease_until__gt=now).exists()
    next_times = list(jobs.filter(state='pending', next_attempt_at__gt=now)
        .values_list('next_attempt_at', flat=True)[:1000])
    attention = jobs.filter(state__in=['blocked', 'failed']).exists()
    return missing or due or working, min(next_times) if next_times else None, attention


def prepare_payload(election_id):
    from .alu_management import setup_digest
    from . import utils
    from .crypto.utils import hash_b64
    from helios_auth.models import User
    # Serialize with native management operations through their existing lock.
    with transaction.atomic():
        AluElectionBinding.objects.select_for_update().filter(election_id=election_id).first()
        election = Election.objects.select_for_update().get(pk=election_id)
        if not election.voting_has_stopped():
            raise RuntimeError('VotingStillOpen')
        if election.num_pending_votes:
            if VoteVerificationJob.objects.filter(cast_vote__voter__election=election,
                    state='pending', cast_vote__quarantined_p=False).exists():
                raise RuntimeError('VerificationPending')
            raise CompletionBlocked('BallotReviewRequired')
        require_policy_decisions(election)
        keys = list(election.trustee_set.all())
        if not keys or any(t.secret_key is None for t in keys):
            # Never delete or replace existing key material to force a tally.
            raise CompletionBlocked('UnsupportedKeyConfiguration')
        if election.result is None:
            if election.encrypted_tally is None:
                now = datetime.datetime.utcnow()
                election.tallying_started_at = election.tallying_started_at or now
                election.save(update_fields=['tallying_started_at'])
                election.compute_tally()
            election.encrypted_tally.init_election(election)
            product = 1
            for key in keys:
                if key.public_key is None or (key.public_key.p,key.public_key.q,key.public_key.g) != (election.public_key.p,election.public_key.q,election.public_key.g):
                    raise CompletionBlocked('InvalidKeyParameters')
                if pow(key.public_key.g, key.secret_key.x, key.public_key.p) != key.public_key.y:
                    raise CompletionBlocked('InvalidKeyBinding')
                product = product * key.public_key.y % election.public_key.p
                factors, proofs = election.encrypted_tally.decryption_factors_and_proofs(key.secret_key)
                if not election.encrypted_tally.verify_decryption_proofs(
                        factors, proofs, key.public_key, algs.EG_fiatshamir_challenge_generator):
                    raise CompletionBlocked('InvalidAggregateProof')
                key.decryption_factors, key.decryption_proofs = factors, proofs
                key.save(update_fields=['decryption_factors', 'decryption_proofs'])
            if product != election.public_key.y:
                raise CompletionBlocked('InvalidAggregateKey')
            election.combine_decryptions()
        raw = utils.to_json(election.toJSONDict(complete=True))
        readers = list(User.objects.filter(user_type='alu').filter(Q(admin_p=True) |
            Q(pk=election.admin_id) | Q(pk__in=election.admins.values('pk')))
            .order_by('user_id').values_list('user_id', flat=True))
        return {'version': 1, 'client_id': settings.ALU_BRIDGE_CLIENT_ID,
            'election_id': election.uuid, 'votes': election.num_cast_votes, 'pending': 0,
            'reader_subjects': readers, 'report': operational_report(election, True),
            'ballot': {'raw': raw, 'fingerprint': hash_b64(raw), 'setup_digest': setup_digest(election),
                'open': False, 'released': False, 'result': election.result}}


def process_next_completion():
    if not enabled():
        return False
    now = datetime.datetime.utcnow()
    for election_id in closed_elections(now).filter(completion_job__isnull=True).values_list('id', flat=True)[:50]:
        ElectionCompletionJob.objects.get_or_create(election_id=election_id, defaults={'next_attempt_at': now})
    with transaction.atomic():
        job = (ElectionCompletionJob.objects.select_for_update(skip_locked=True)
            .filter(election__in=closed_elections(now))
            .filter(Q(state='pending', next_attempt_at__lte=now) | Q(state='working', lease_until__lte=now))
            .order_by('next_attempt_at', 'id').first())
        if not job:
            return False
        job.state, job.lease = 'working', uuid.uuid4()
        job.lease_until = now + datetime.timedelta(minutes=10)
        job.attempts += 1
        job.save()
    try:
        payload = job.payload or prepare_payload(job.election_id)
        if job.payload is None:
            ElectionCompletionJob.objects.filter(pk=job.pk, lease=job.lease).update(payload=payload)
        response = requests.post(https_origin(settings.ALU_BRIDGE_APP_ORIGIN) + '/api/helios/completed-election',
            headers={'Authorization': 'Bearer ' + settings.ALU_BRIDGE_SECRET},
            json=payload, timeout=30, allow_redirects=False)
        if response.status_code != 200 or response.json().get('saved') is not True:
            raise RuntimeError('ArchiveNotAcknowledged')
        ElectionCompletionJob.objects.filter(pk=job.pk, lease=job.lease).update(
            state='saved', saved_at=datetime.datetime.utcnow(), lease_until=None, last_error_code='')
    except Exception as error:
        blocked = isinstance(error, CompletionBlocked) or (
            isinstance(error, PermissionDenied) and str(error) == 'Ballots require an explicit election-policy decision before tallying.')
        state = 'blocked' if blocked else 'failed' if job.attempts >= 8 else 'pending'
        delay = min(3600, 5 * 4 ** min(job.attempts - 1, 5))
        ElectionCompletionJob.objects.filter(pk=job.pk, lease=job.lease).update(state=state,
            lease_until=None, next_attempt_at=datetime.datetime.utcnow()+datetime.timedelta(seconds=delay),
            last_error_code=type(error).__name__)
        # Advisory UI status contains no exception text or sensitive data. The
        # final archive itself uses the durable acknowledged delivery above.
        try:
            election = Election.objects.only('uuid').get(pk=job.election_id)
            requests.post(https_origin(settings.ALU_BRIDGE_APP_ORIGIN) + '/api/helios/completion-status',
                headers={'Authorization': 'Bearer ' + settings.ALU_BRIDGE_SECRET},
                json={'client_id': settings.ALU_BRIDGE_CLIENT_ID, 'election_id': election.uuid,
                    'state': state, 'reason': 'review_required' if blocked else 'temporarily_unavailable'},
                timeout=5, allow_redirects=False)
        except Exception:
            pass
    return True
