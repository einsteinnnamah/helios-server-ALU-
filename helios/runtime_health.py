"""Private metadata probe used by the Cloudflare recovery alarm."""
import hmac
import datetime
import os
import re

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from .models import VoteVerificationJob, VoteConfirmationEmail, Election


class ContainerHealthMiddleware:
    """Answer SDK startup probes before HTTPS redirects, on internal hosts only."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (request.method in ('GET', 'HEAD') and request.path == '/' and
                request.get_host() in ('ping', 'containerstarthealthcheck')):
            response = HttpResponse('ready', content_type='text/plain')
            response['Cache-Control'] = 'no-store'
            return response
        response = self.get_response(request)
        if request.method == 'GET' and request.path.endswith('/ui/ballot'):
            # Non-sensitive deployment metadata, including on an unknown
            # election's 404. Operators can verify placement without SSH keys,
            # voter identity, a real ballot, or any additional database query.
            host = settings.DATABASES['default'].get('HOST', '')
            region = re.search(r'\b((?:us|eu|ap|ca|sa|me|af|il)-(?:east|west|central|south|north|southeast|northeast)-\d)\b', host)
            response['X-Voting-Database-Region'] = region[1] if region else 'unknown'
            for header, variable in [('X-Voting-Location', 'CLOUDFLARE_LOCATION'),
                                     ('X-Voting-Region', 'CLOUDFLARE_REGION')]:
                response[header] = re.sub(r'[^A-Za-z0-9 _-]', '', os.environ.get(variable, 'unknown'))[:80]
            response['X-Voting-Database-Pooler'] = 'transaction' if '-pooler' in host else 'direct'
        return response


@require_GET
def verification_state(request):
    secret = getattr(settings, 'RECOVERY_SECRET', '')
    if not secret or not hmac.compare_digest(
            request.headers.get('Authorization', ''), 'Bearer ' + secret):
        response = JsonResponse({'error': 'Unauthorized'}, status=401)
    else:
        active = (VoteVerificationJob.objects.filter(state='pending',
            cast_vote__voter__election__deleted_at=None)
            .filter(Q(cast_vote__quarantined_p=False) |
                    Q(cast_vote__released_from_quarantine_at__isnull=False)))
        pending = active.exists()
        attention = VoteVerificationJob.objects.filter(state='failed', cast_vote__voter__election__deleted_at=None).exists()
        now = datetime.datetime.utcnow()
        # Only runnable background work should pin a billable container. Failed
        # jobs and quarantined ballots need an operator, not endless polling.
        keep_alive = VoteConfirmationEmail.objects.filter(state__in=['pending', 'sending']).exists() or pending
        next_wake = None
        # Requests already renew the SDK's ten-minute idle window. An open or
        # unpublished election must not turn that into continuous paid uptime.
        # Prewarm once around a future scheduled opening, then use activity.
        # Helios dates are naive UTC; all elections share the same container.
        for election in Election.objects.filter(frozen_at__isnull=False,
                result_released_at__isnull=True, deleted_at__isnull=True,
                voting_started_at__isnull=True, voting_ended_at__isnull=True,
                tallying_started_at__isnull=True, voting_starts_at__isnull=False).only(
                'voting_starts_at', 'voting_ends_at', 'voting_extended_until'):
            start = election.voting_starts_at
            end = election.voting_extended_until or election.voting_ends_at
            if end and end <= now:
                continue
            if start - datetime.timedelta(minutes=5) <= now < start + datetime.timedelta(minutes=5):
                keep_alive = True
            elif start > now + datetime.timedelta(minutes=5):
                wake = int((start - datetime.timedelta(minutes=5)).replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
                next_wake = wake if next_wake is None else min(next_wake, wake)
        response = JsonResponse({'pending': pending, 'needs_attention': attention,
            'keep_alive': keep_alive, 'next_wake_at': next_wake})
    response['Cache-Control'] = 'no-store'
    return response
