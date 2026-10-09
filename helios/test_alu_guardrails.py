from django.test import SimpleTestCase, RequestFactory
from django.core.cache import cache
from django.http import HttpResponse
from helios.alu_guardrails import AluRequestGuardrails


class AluGuardrailTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.middleware = AluRequestGuardrails(lambda request: HttpResponse('ok'))

    def request(self, subject='student', **meta):
        request = self.factory.post('/helios/elections/test/cast', **meta)
        request.session = {'alu_election': 'test', 'user': {'type': 'alu', 'user_id': subject}}
        return request

    def test_repeated_casts_are_limited_per_account(self):
        for _ in range(20):
            self.assertEqual(self.middleware(self.request()).status_code, 200)
        refused = self.middleware(self.request())
        self.assertEqual(refused.status_code, 429)
        self.assertEqual(refused['Retry-After'], '60')
        self.assertEqual(self.middleware(self.request('other-student')).status_code, 200)

    def test_forwarded_headers_cannot_bypass_account_limit(self):
        for _ in range(20):
            self.middleware(self.request())
        self.assertEqual(self.middleware(self.request(HTTP_X_FORWARDED_FOR='different')).status_code, 429)

    def test_oversized_or_invalid_request_refused(self):
        self.assertEqual(self.middleware(self.request(CONTENT_LENGTH=str(2097153))).status_code, 413)
        self.assertEqual(self.middleware(self.request(CONTENT_LENGTH='invalid')).status_code, 400)

    def test_reading_receipts_is_not_throttled(self):
        for _ in range(25):
            self.assertEqual(self.middleware(self.factory.get('/helios/elections/test/ui/receipt/tracker')).status_code, 200)
