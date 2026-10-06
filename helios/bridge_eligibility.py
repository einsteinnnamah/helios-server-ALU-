"""Fresh, authenticated membership checks; ballot contents never leave Helios."""
import datetime

import requests
from django.conf import settings
from django.core.exceptions import PermissionDenied
from helios_auth.bridge_protocol import eligible_identity, https_origin


def bridge_election(election):
  return election.uuid in settings.ALU_BRIDGE_ELECTIONS


def statuses(election, voters):
  result = {}
  for offset in range(0, len(voters), 50):
    batch = voters[offset:offset + 50]
    try:
      response = requests.post(https_origin(settings.ALU_BRIDGE_APP_ORIGIN) + '/api/helios/eligibility',
        headers={'Authorization': 'Bearer ' + settings.ALU_BRIDGE_SECRET},
        json={'client_id': settings.ALU_BRIDGE_CLIENT_ID, 'election_id': election.uuid, 'voters': batch},
        timeout=15, allow_redirects=False)
      if response.status_code != 200:
        raise ValueError()
      data = response.json()
      if data['binding'] != {'client_id': settings.ALU_BRIDGE_CLIENT_ID, 'election_id': election.uuid}:
        raise ValueError()
      rows = data['voters']
      expected = {v['subject'] for v in batch}
      if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError()
      for row in rows:
        if (not isinstance(row, dict) or row.get('subject') not in expected or
            type(row.get('student')) is not bool or type(row.get('committee')) is not bool or
            not isinstance(row.get('events'), list) or
            any(not isinstance(event, str) or not event.isdigit() or len(event) > 30 for event in row['events'])):
          raise ValueError()
        expected.remove(row['subject'])
        result[row['subject']] = row
    except (requests.RequestException, ValueError, KeyError, TypeError):
      # Fail closed. Never log response bodies, headers, credentials or identity.
      raise PermissionDenied('Voting eligibility could not be checked. Please retry.') from None
  return result


def require_voting_access(request, election, user):
  if not bridge_election(election):
    return
  # Independent Helios identity/session/election checks precede the fresh query.
  import time
  if (not user or user.user_type != 'alu' or
      request.session.get('alu_election') != election.uuid or
      request.session.get('alu_access_kind') != 'voter' or
      request.session.get('alu_session_expires_at', 0) <= time.time() or
      not eligible_identity({'subject': user.user_id, 'email': user.info.get('email'),
                             'email_verified': user.info.get('email_verified')})):
    raise PermissionDenied('A student voting login is required.')
  row = statuses(election, [{'subject': user.user_id, 'cast_at': None}])[user.user_id]
  if not row['student'] or row['committee']:
    # Preserve this login and all authorized committee/admin permissions.
    refresh_policy_reviews(election)
    raise PermissionDenied('Committee members cannot vote in this election.')


def refresh_policy_reviews(election):
  if not bridge_election(election):
    return
  from helios.models import BallotPolicyReview
  voters = list(election.voter_set.exclude(vote=None).select_related('user'))
  # The earliest verified cast detects joining after ANY retained cast, including
  # superseded ballots. No ballot is deleted, invalidated or replaced here.
  requests_to_check = []
  for voter in voters:
    if not voter.user or voter.user.user_type != 'alu':
      raise PermissionDenied('An unbound voter requires election-policy review.')
    cast = voter.castvote_set.filter(verified_at__isnull=False).order_by('cast_at').first()
    if not cast:
      raise PermissionDenied('A ballot without a verified cast requires election-policy review.')
    timestamp = cast.cast_at.replace(tzinfo=datetime.timezone.utc).isoformat()
    requests_to_check.append({'subject': voter.user.user_id, 'cast_at': timestamp})
  current = statuses(election, requests_to_check)
  for voter in voters:
    row = current[voter.user.user_id]
    events = row['events']
    if row['committee'] and not events:
      events = ['current']
    if not row['student']:
      events = events + ['identity']
    for event in events:
      BallotPolicyReview.objects.get_or_create(election=election, voter=voter,
        event_key=event, defaults={'reason': 'Committee membership after a cast or current eligibility conflict.'})


def require_policy_decisions(election):
  if not bridge_election(election):
    return
  from helios.models import BallotPolicyReview
  refresh_policy_reviews(election)
  if BallotPolicyReview.objects.filter(election=election, decision='pending').exists():
    raise PermissionDenied('Ballots require an explicit election-policy decision before tallying.')
