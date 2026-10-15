from datetime import timedelta
from unittest.mock import patch

import httpx2 as httpx
from django.test import TestCase, override_settings
from django.utils import timezone
from openai import RateLimitError

from portal.models import AnalysisJob, Machine, PlatformSettings, User
from portal.processing import MAX_RATE_LIMIT_RETRY_SECONDS, process_next_job


@override_settings(OPENAI_API_KEY="test-not-a-real-key", OPENAI_MODEL="gpt-4.1-mini")
class RateLimitRetryTimingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="retry-timing@example.com", password="tests-only-pass-4821")
        self.machine = Machine.objects.create(owner=self.user, title="Equipo de prueba")
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=300000, ai_max_attempts=2)
        self.sequence = 0

    def queued_job(self):
        self.sequence += 1
        return AnalysisJob.objects.create(
            machine=self.machine, requested_by=self.user, revision=self.machine.revision,
            asset_ids=[], mode="description", fingerprint=f"{self.sequence:064x}", model="gpt-4.1-mini",
            reserved_tokens=18_000,
            result={"attempt_limit": 2, "reservation_per_attempt": 9_000, "research_requested": False},
        )

    @staticmethod
    def rate_limited(retry_after=None, *, insufficient_quota=False):
        headers = {} if retry_after is None else {"retry-after": retry_after}
        response = httpx.Response(429, headers=headers,
                                  request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
        body = ({"error": {"code": "insufficient_quota", "type": "insufficient_quota"}}
                if insufficient_quota else {"error": {"message": "private provider body"}})
        return RateLimitError("private provider exception", response=response, body=body)

    def run_failure(self, error):
        job = self.queued_job()
        before = timezone.now()
        with patch("portal.processing.process_analysis", side_effect=error):
            self.assertTrue(process_next_job())
        job.refresh_from_db()
        return job, before

    def assert_delay(self, job, before, expected):
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.result["last_failure_kind"], "rate_limited")
        self.assertGreaterEqual(job.locked_at, before + timedelta(seconds=expected - 1))
        self.assertLessEqual(job.locked_at, timezone.now() + timedelta(seconds=expected + 1))
        self.assertNotIn("private provider", str(job.result))
        self.assertNotIn("private provider", job.error)

    def test_retry_after_defers_the_next_attempt(self):
        job, before = self.run_failure(self.rate_limited("120"))
        self.assert_delay(job, before, 120)

    def test_invalid_retry_after_keeps_existing_backoff(self):
        job, before = self.run_failure(self.rate_limited("not-a-delay"))
        self.assert_delay(job, before, 30)

    def test_retry_after_is_capped_at_a_safe_limit(self):
        job, before = self.run_failure(self.rate_limited("9999"))
        self.assert_delay(job, before, MAX_RATE_LIMIT_RETRY_SECONDS)

    def test_insufficient_quota_is_terminal_and_never_scheduled_for_retry(self):
        job, _ = self.run_failure(self.rate_limited("120", insufficient_quota=True))
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.attempts, 1)
        self.assertIsNone(job.locked_at)
        self.assertEqual(job.result["provider_error_code"], "billing_unavailable")
        self.assertEqual(job.reserved_tokens, 0)
