"""A quota reset grants a new window without erasing usage or active commitments."""
from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from portal.ai_quota import daily_budget_jobs, daily_quota_jobs, quota_window_start
from portal.models import AnalysisJob, AuditEvent, Machine, PlatformSettings, User
from portal.processing import _can_spend_step, _ensure_execution_reservation, enqueue_analysis
from portal.research import UsageTotals


NOW = datetime(2026, 9, 28, 17, tzinfo=datetime_timezone.utc)
RESET = NOW - timedelta(hours=1)
MIDNIGHT = datetime(2026, 9, 28, 6, tzinfo=datetime_timezone.utc)
DESCRIPTION_COST = 9_000


@override_settings(TIME_ZONE="America/Mexico_City")
class QuotaWindowTests(SimpleTestCase):
    def test_reset_only_moves_the_start_of_the_current_local_day_forward(self):
        with timezone.override("America/Mexico_City"):
            for reset, expected in ((None, MIDNIGHT), (MIDNIGHT - timedelta(seconds=1), MIDNIGHT),
                                    (RESET, RESET), (NOW + timedelta(seconds=1), MIDNIGHT)):
                with self.subTest(reset=reset):
                    limits = PlatformSettings(ai_usage_reset_at=reset)
                    self.assertEqual(quota_window_start(limits, NOW), expected)

    def test_next_local_midnight_replaces_yesterdays_reset(self):
        limits = PlatformSettings(ai_usage_reset_at=RESET)
        with timezone.override("America/Mexico_City"):
            # UTC has already changed dates, but Mexico is still on the reset day.
            self.assertEqual(quota_window_start(limits, MIDNIGHT + timedelta(days=1, microseconds=-1)), RESET)
            self.assertEqual(quota_window_start(limits, MIDNIGHT + timedelta(days=1)), MIDNIGHT + timedelta(days=1))


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-4.1-mini",
                   TIME_ZONE="America/Mexico_City")
class QuotaResetAccountingTests(TestCase):
    def setUp(self):
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.owner = User.objects.create_user(email="quota-reset@example.invalid")
        self.machine = Machine.objects.create(owner=self.owner, data={"brand": "Bobcat", "model": "S650"})
        self.limits = PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_usage_reset_at=RESET)

    def job(self, name, *, created=None, finished=None, status="completed", owner=None, **values):
        job = AnalysisJob.objects.create(machine=self.machine, requested_by=owner or self.owner,
            revision=self.machine.revision, fingerprint=name, mode="description", model="gpt-4.1-mini",
            status=status, finished_at=finished, **values)
        AnalysisJob.objects.filter(pk=job.pk).update(created_at=created or RESET - timedelta(minutes=10))
        job.refresh_from_db()
        return job

    def enqueue(self, *, fresh_machine=False):
        machine = self.machine
        if fresh_machine:
            machine = Machine.objects.create(owner=self.owner, data={"brand": "Bobcat", "model": "S650"})
        return enqueue_analysis(machine, self.owner, mode="description", authorize_ai=True)

    def budget(self, limit):
        self.limits.ai_daily_token_limit = limit
        self.limits.save(update_fields=["ai_daily_token_limit"])

    def test_reset_reopens_exhausted_token_budget_without_erasing_usage_or_audit(self):
        previous = self.job("previous-usage", finished=RESET - timedelta(minutes=1),
                            input_tokens=190_000, output_tokens=10_000, attempts=2,
                            result={"usage": {"input_tokens": 190_000, "output_tokens": 10_000}})
        event = AuditEvent.objects.create(actor=self.owner, action="analysis.completed",
            object_type="AnalysisJob", object_id=str(previous.pk), metadata={"input_tokens": 190_000})
        self.limits.ai_usage_reset_at = None
        self.limits.save(update_fields=["ai_usage_reset_at"])
        with patch("openai.OpenAI") as provider:
            with self.assertRaisesMessage(ValidationError, "No hay capacidad de análisis"):
                self.enqueue()
            self.limits.ai_usage_reset_at = RESET
            self.limits.save(update_fields=["ai_usage_reset_at"])
            admitted = self.enqueue()
        provider.assert_not_called()
        previous.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual((previous.input_tokens, previous.output_tokens, previous.attempts), (190_000, 10_000, 2))
        self.assertEqual(previous.result["usage"], {"input_tokens": 190_000, "output_tokens": 10_000})
        self.assertEqual(event.metadata, {"input_tokens": 190_000})
        self.assertEqual(admitted.status, "queued")
        self.assertEqual(daily_quota_jobs(self.limits, NOW).count(), 1)
        self.assertEqual(AnalysisJob.objects.count(), 2)
        self.assertEqual(self.limits.ai_daily_token_limit, 200_000)

    def test_reset_reopens_fifty_used_slots_without_deleting_the_old_jobs(self):
        for number in range(50):
            self.job(f"old-slot-{number}", finished=RESET - timedelta(minutes=1))
        admitted = self.enqueue()
        self.assertEqual(list(daily_quota_jobs(self.limits, NOW)), [admitted])
        self.assertEqual(AnalysisJob.objects.count(), 51)

    def test_reset_keeps_queued_and_running_jobs_in_the_token_budget(self):
        queued = self.job("old-queued", status="queued", reserved_tokens=80_000)
        running = self.job("old-running", status="running", reserved_tokens=111_001,
                           input_tokens=1_000, locked_at=NOW, attempts=1)
        self.assertCountEqual(daily_budget_jobs(self.limits, NOW), [queued, running])
        self.assertFalse(daily_quota_jobs(self.limits, NOW).exists())
        with patch("openai.OpenAI") as provider, self.assertRaisesMessage(ValidationError, "No hay capacidad de análisis"):
            self.enqueue()
        provider.assert_not_called()
        self.assertEqual(AnalysisJob.objects.count(), 2)

    def test_job_started_before_reset_but_finished_after_it_is_still_charged(self):
        finished_late = self.job("crossed-reset", finished=RESET + timedelta(minutes=1), input_tokens=195_000)
        self.assertEqual(list(daily_budget_jobs(self.limits, NOW)), [finished_late])
        self.assertFalse(daily_quota_jobs(self.limits, NOW).exists())
        with self.assertRaisesMessage(ValidationError, "No hay capacidad de análisis"):
            self.enqueue()

    def test_cutoff_is_inclusive_for_created_and_finished_jobs(self):
        created_at_reset = self.job("created-at-reset", created=RESET, finished=RESET)
        finished_at_reset = self.job("finished-at-reset", finished=RESET)
        before = self.job("before-reset", finished=RESET - timedelta(microseconds=1))
        self.assertEqual(list(daily_quota_jobs(self.limits, NOW)), [created_at_reset])
        self.assertCountEqual(daily_budget_jobs(self.limits, NOW), [created_at_reset, finished_at_reset])
        self.assertNotIn(before, daily_budget_jobs(self.limits, NOW))

    def test_next_day_releases_completed_usage_but_keeps_an_unfinished_reservation(self):
        self.job("completed-on-reset-day", created=RESET, finished=NOW, input_tokens=150_000)
        active = self.job("still-active-next-day", status="queued", reserved_tokens=40_000)
        next_day = MIDNIGHT + timedelta(days=1)
        self.assertFalse(daily_quota_jobs(self.limits, next_day).exists())
        self.assertEqual(list(daily_budget_jobs(self.limits, next_day)), [active])

    def test_fiftieth_user_job_is_admitted_and_fifty_first_is_rejected(self):
        for number in range(49):
            self.job(f"user-slot-{number}", created=RESET, finished=NOW)
        with patch("openai.OpenAI") as provider:
            admitted = self.enqueue()
            with self.assertRaisesMessage(ValidationError, "Alcanzaste el límite diario"):
                self.enqueue(fresh_machine=True)
        provider.assert_not_called()
        self.assertEqual(admitted.status, "queued")
        self.assertEqual(daily_quota_jobs(self.limits, NOW).filter(requested_by=self.owner).count(), 50)

    def test_fiftieth_global_job_is_admitted_and_fifty_first_is_rejected(self):
        other = User.objects.create_user(email="quota-other@example.invalid")
        for number in range(49):
            self.job(f"global-slot-{number}", owner=other, created=RESET, finished=NOW)
        with patch("openai.OpenAI") as provider:
            admitted = self.enqueue()
            with self.assertRaisesMessage(ValidationError, "límite diario de la plataforma"):
                self.enqueue(fresh_machine=True)
        provider.assert_not_called()
        self.assertEqual(admitted.status, "queued")
        self.assertEqual(daily_quota_jobs(self.limits, NOW).count(), 50)
        self.assertEqual(daily_quota_jobs(self.limits, NOW).filter(requested_by=self.owner).count(), 1)

    def test_worker_step_ignores_settled_pre_reset_usage_but_honors_late_finishes(self):
        previous = self.job("old-budget", finished=RESET - timedelta(seconds=1), input_tokens=190_000)
        running = self.job("spending-now", status="running", reserved_tokens=DESCRIPTION_COST,
            attempts=1, locked_at=NOW, result={"reservation_per_attempt": DESCRIPTION_COST, "attempt_limit": 1})
        self.budget(DESCRIPTION_COST)
        with patch("openai.OpenAI") as provider:
            self.assertTrue(_can_spend_step(running, UsageTotals(), DESCRIPTION_COST))
            # Existing work finishes after the reset and must re-enter accounting.
            AnalysisJob.objects.filter(pk=previous.pk).update(finished_at=RESET)
            self.assertFalse(_can_spend_step(running, UsageTotals(), DESCRIPTION_COST))
        provider.assert_not_called()

    def test_worker_step_cannot_spend_another_old_running_jobs_reservation(self):
        self.job("other-active", status="running", reserved_tokens=DESCRIPTION_COST, locked_at=NOW)
        running = self.job("active-current", status="running", reserved_tokens=DESCRIPTION_COST,
            attempts=1, locked_at=NOW, result={"reservation_per_attempt": DESCRIPTION_COST, "attempt_limit": 1})
        self.budget(DESCRIPTION_COST)
        self.assertFalse(_can_spend_step(running, UsageTotals(), DESCRIPTION_COST))

    def test_reservation_reconciliation_uses_reset_window_and_keeps_other_old_reservations(self):
        self.job("settled-old-usage", finished=RESET - timedelta(seconds=1), input_tokens=190_000)
        self.job("old-active", status="running", reserved_tokens=DESCRIPTION_COST, locked_at=NOW)
        queued = self.job("legacy-upgrade", status="queued", reserved_tokens=1_000,
                          result={"reservation_per_attempt": 1_000, "attempt_limit": 2})
        self.budget(2 * DESCRIPTION_COST)
        with patch("openai.OpenAI") as provider:
            self.assertTrue(_ensure_execution_reservation(queued, self.limits, NOW))
        provider.assert_not_called()
        queued.refresh_from_db()
        self.assertEqual(queued.reserved_tokens, DESCRIPTION_COST)
        self.assertEqual(queued.result["attempt_limit"], 1)
        self.assertEqual(queued.status, "queued")

    def test_reservation_reconciliation_rejects_a_post_reset_budget_exhaustion(self):
        self.job("finished-after-reset", finished=RESET, input_tokens=DESCRIPTION_COST)
        queued = self.job("cannot-upgrade", status="queued", reserved_tokens=1_000,
                          result={"reservation_per_attempt": 1_000, "attempt_limit": 2})
        self.budget(DESCRIPTION_COST)
        self.assertFalse(_ensure_execution_reservation(queued, self.limits, NOW))
        queued.refresh_from_db()
        self.assertEqual((queued.status, queued.reserved_tokens, queued.attempts), ("failed", 0, 0))
        self.assertEqual(queued.finished_at, NOW)
