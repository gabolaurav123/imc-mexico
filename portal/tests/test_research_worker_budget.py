"""Queue contracts for the expanded research pipeline; no provider traffic."""
from datetime import timedelta
from unittest.mock import patch

import httpx2
from openai import APIConnectionError
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from portal.models import AnalysisJob, Machine, PlatformSettings, User
from portal.processing import (
    MIN_JOB_LEASE_SECONDS, PROMPT_VERSION, _claim_job, _job_lease_seconds,
    _reservation, enqueue_analysis, process_next_job,
)
from portal.research import RESEARCH_RESERVATION, UsageTotals, empty_research
from portal.valuation import VALUATION_RESERVATION


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_TIMEOUT=90,
                   AI_JOB_STALE_SECONDS=300)
class ResearchWorkerBudgetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="worker-budget@example.invalid")
        self.machine = Machine.objects.create(owner=self.user, data={"brand": "Caterpillar", "model": "420F2"})
        self.limits = PlatformSettings.objects.create(pk=1, ai_enabled=True,
            ai_daily_token_limit=RESEARCH_RESERVATION * 5, ai_max_attempts=2)

    def enqueue(self):
        return enqueue_analysis(self.machine, self.user, mode="description", research=True, authorize_ai=True)

    def legacy(self, *, status="queued", attempts=0, attempt_limit=2, per_attempt=20000):
        remaining = attempt_limit - attempts + int(status == "running")
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.user,
            revision=self.machine.revision, fingerprint="legacy-budget", mode="description",
            prompt_version="imc-vision-research-2026-09-v9", model="gpt-4.1-mini",
            status=status, attempts=attempts, reserved_tokens=per_attempt * remaining,
            locked_at=timezone.now() - timedelta(hours=1) if status == "running" else None,
            result={"research_requested": True, "research_description_only": True, "attempt_limit": attempt_limit})

    def test_new_jobs_reserve_every_research_stage_for_each_allowed_attempt(self):
        job = self.enqueue()
        self.assertEqual(job.prompt_version, PROMPT_VERSION)
        self.assertEqual(job.result["reservation_per_attempt"], RESEARCH_RESERVATION)
        self.assertEqual(job.reserved_tokens, 2 * RESEARCH_RESERVATION)
        self.assertEqual(_reservation(3, "analysis", True), 3 * 12200 + RESEARCH_RESERVATION + VALUATION_RESERVATION)
        self.assertEqual(_reservation(0, "description", False), 9000)
        self.limits.refresh_from_db()
        self.assertEqual(self.limits.ai_daily_token_limit, 5 * RESEARCH_RESERVATION)

    def test_admission_rejects_insufficient_full_pipeline_budget_before_any_remote_call(self):
        self.limits.ai_daily_token_limit = RESEARCH_RESERVATION - 1
        self.limits.save()
        with patch("openai.OpenAI") as provider, self.assertRaises(ValidationError):
            self.enqueue()
        provider.assert_not_called()
        self.assertFalse(AnalysisJob.objects.exists())

    def test_legacy_queued_job_reserves_the_new_cost_before_claim(self):
        job = self.legacy()
        claimed = _claim_job()
        self.assertEqual(claimed.pk, job.pk)
        self.assertEqual(claimed.attempts, 1)
        self.assertEqual(claimed.reserved_tokens, 2 * RESEARCH_RESERVATION)
        self.assertEqual(claimed.result["reservation_per_attempt"], RESEARCH_RESERVATION)
        self.limits.refresh_from_db()
        self.assertEqual(self.limits.ai_daily_token_limit, 5 * RESEARCH_RESERVATION)

    def test_legacy_upgrade_counts_other_reservations_and_can_reduce_to_one_attempt(self):
        job = self.legacy()
        self.limits.ai_daily_token_limit = 2 * RESEARCH_RESERVATION
        self.limits.save()
        AnalysisJob.objects.create(machine=self.machine, requested_by=self.user,
            revision=self.machine.revision,
            fingerprint="other-budget", status="running", reserved_tokens=RESEARCH_RESERVATION,
            attempts=1, locked_at=timezone.now())
        claimed = _claim_job()
        self.assertEqual(claimed.pk, job.pk)
        self.assertEqual(claimed.result["attempt_limit"], 1)
        self.assertEqual(claimed.reserved_tokens, RESEARCH_RESERVATION)

    def test_legacy_upgrade_without_capacity_fails_without_claim_or_provider(self):
        job = self.legacy()
        self.limits.ai_daily_token_limit = RESEARCH_RESERVATION - 1
        self.limits.save()
        with patch("portal.processing.process_analysis") as process, patch("openai.OpenAI") as provider:
            self.assertFalse(process_next_job())
        process.assert_not_called()
        provider.assert_not_called()
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts, job.reserved_tokens), ("failed", 0, 0))
        self.assertIn("No hay capacidad", job.error)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.status, "draft")

    def test_long_active_pipeline_is_not_reclaimed_at_old_five_minute_boundary(self):
        job = self.enqueue()
        _claim_job()
        AnalysisJob.objects.filter(pk=job.pk).update(locked_at=timezone.now() - timedelta(seconds=450))
        self.assertIsNone(_claim_job())
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts, job.input_tokens), ("running", 1, 0))
        self.assertGreaterEqual(_job_lease_seconds(), MIN_JOB_LEASE_SECONDS)

    @override_settings(OPENAI_TIMEOUT=900)
    def test_lease_preserves_io_allowance_for_a_longer_configured_vision_timeout(self):
        self.assertEqual(_job_lease_seconds(), MIN_JOB_LEASE_SECONDS + 900 - 90)

    def test_expired_new_lease_retries_once_and_accounts_one_reserved_attempt_each_time(self):
        job = self.enqueue()
        _claim_job()
        expired = timezone.now() - timedelta(seconds=MIN_JOB_LEASE_SECONDS + 1)
        AnalysisJob.objects.filter(pk=job.pk).update(locked_at=expired)
        retry = _claim_job()
        self.assertEqual((retry.attempts, retry.input_tokens, retry.reserved_tokens),
                         (2, RESEARCH_RESERVATION, RESEARCH_RESERVATION))
        AnalysisJob.objects.filter(pk=job.pk).update(locked_at=expired)
        self.assertIsNone(_claim_job())
        job.refresh_from_db()
        self.assertEqual((job.status, job.input_tokens, job.reserved_tokens),
                         ("failed", 2 * RESEARCH_RESERVATION, 0))

    def test_legacy_expired_attempt_accounts_old_cost_then_reserves_new_retry_cost(self):
        job = self.legacy(status="running", attempts=1)
        retry = _claim_job()
        self.assertEqual(retry.pk, job.pk)
        self.assertEqual((retry.attempts, retry.input_tokens, retry.reserved_tokens),
                         (2, 20000, RESEARCH_RESERVATION))
        self.assertEqual(retry.result["reservation_per_attempt"], RESEARCH_RESERVATION)

    def test_reduced_admin_attempt_limit_does_not_double_charge_old_lease(self):
        job = self.legacy(status="running", attempts=1)
        self.limits.ai_max_attempts = 1
        self.limits.save()
        self.assertIsNone(_claim_job())
        job.refresh_from_db()
        self.assertEqual((job.status, job.input_tokens, job.reserved_tokens), ("failed", 20000, 0))

    def test_transient_failure_retains_only_reserved_retry_and_records_known_partial_usage(self):
        job = self.enqueue()
        failure = APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))
        failure.accounted_usage = UsageTotals(input_tokens=430, output_tokens=70)
        with patch("portal.processing.process_analysis", side_effect=failure):
            self.assertTrue(process_next_job())
            self.assertFalse(process_next_job())
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts, job.input_tokens, job.output_tokens, job.reserved_tokens),
                         ("queued", 1, 430, 70, RESEARCH_RESERVATION))
        self.assertGreater(job.locked_at, timezone.now())

    def test_partial_multistage_usage_survives_completion_without_research_retry(self):
        job = self.enqueue()
        usage = UsageTotals(input_tokens=32000, output_tokens=800, estimated_tokens=28000, web_search_calls=3)
        research = empty_research("degraded")
        research["usage"] = usage.as_dict()
        with patch("openai.OpenAI") as provider, patch("portal.processing.research_machine", return_value=(research, usage)):
            self.assertTrue(process_next_job())
        provider.return_value.responses.parse.assert_not_called()
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts, job.input_tokens, job.output_tokens, job.reserved_tokens),
                         ("completed", 1, 32000, 800, 0))
        self.assertEqual(job.result["usage"], usage.as_dict())
        self.assertEqual(job.result["research"]["status"], "degraded")

    def test_old_worker_result_cannot_replace_a_newer_lease(self):
        job = self.enqueue()

        def late_response(claimed):
            AnalysisJob.objects.filter(pk=claimed.pk).update(locked_at=claimed.locked_at + timedelta(seconds=1))
            return {"data": {"description": "late"}}, UsageTotals(input_tokens=100, output_tokens=30)

        with patch("portal.processing.process_analysis", side_effect=late_response):
            self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.assertEqual((job.status, job.input_tokens), ("running", 0))
        self.assertNotIn("data", job.result)
