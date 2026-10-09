"""Bound ALU demo request work; this is not an edge DDoS firewall."""
import hashlib
import time
from django.core.cache import cache
from django.http import HttpResponse


class AluRequestGuardrails:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method != 'POST' or not request.path.startswith(('/helios/', '/auth/alu')):
            return self.get_response(request)
        try:
            size = int(request.META.get('CONTENT_LENGTH') or 0)
        except (TypeError, ValueError):
            return self.refuse(400, 'Invalid request length')
        if size < 0 or size > 2 * 1024 * 1024:
            return self.refuse(413, 'Request too large')
        session = getattr(request, 'session', {})
        user = session.get('user') or {}
        # Identity is from Django's server-side session, never an IP/header or
        # browser-supplied subject. Avoid campus-wide limits on shared NAT IPs.
        if session.get('alu_election') and isinstance(user, dict) and user.get('type') == 'alu':
            subject = user.get('user_id')
            if isinstance(subject, str) and request.path.rstrip('/').endswith(('/cast', '/cast_confirm', '/register', '/ui/submit')):
                key = 'alu-cast:' + hashlib.sha256(subject.encode()).hexdigest() + ':' + str(int(time.time()) // 60)
                if cache.add(key, 1, timeout=120):
                    count = 1
                else:
                    try:
                        count = cache.incr(key)
                    except ValueError:
                        return self.refuse(429, 'Please wait before retrying')
                if count > 20:
                    return self.refuse(429, 'Please wait before retrying')
        return self.get_response(request)

    @staticmethod
    def refuse(status, message):
        response = HttpResponse(message, status=status)
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        if status == 429:
            response['Retry-After'] = '60'
        return response
