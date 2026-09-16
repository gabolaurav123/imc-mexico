"""Deleting/restoring a draft cannot restart paid work or apply a late result."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from portal.models import AnalysisJob, AnalyticsEvent, Machine, PlatformSettings, User
from portal.processing import (DraftAnalysisCancelled, _claim_job, enqueue_analysis,
                               process_analysis, process_next_job)
from portal.services import apply_analysis_automatically, delete_draft, restore_draft


@override_settings(OPENAI_API_KEY="only-a-test-key", OPENAI_MODEL="gpt-4.1-mini")
class DeletedDraftJobTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="draft-jobs@example.invalid", password="test-only-9418")
        self.machine = Machine.objects.create(owner=self.owner, title="Título humano", data={"brand": "Marca humana"})
        self.limits = PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=18000,
                                                      ai_max_attempts=2, analytics_enabled=True)
        self.result = {"data": {"description": "Propuesta tardía que no debe aplicarse."},
                       "provenance": {"description": {"source": "visual_proposal", "review": "needs_review"}},
                       "fields": [], "plates": [], "warnings": [], "questions": []}
        self.usage = SimpleNamespace(input_tokens=120, output_tokens=45)

    def enqueue(self, machine=None):
        machine = machine or self.machine
        return enqueue_analysis(machine, self.owner, mode="description", authorize_ai=True,
            auto_apply=True, expected_revision=machine.revision,
            analytics_context={"session_hash": "a" * 64, "_consent": True})

    def delete(self, restore=False):
        current = Machine.all_objects.get(pk=self.machine.pk)
        current = delete_draft(current, self.owner, current.revision)
        if restore:
            current = restore_draft(current, self.owner, current.revision)
        return current

    def assert_cancelled(self, job):
        job.refresh_from_db()
        self.assertTrue(job.result["draft_deleted"])
        self.assertEqual(job.application_result["reason"], "draft_deleted")
        self.assertEqual(job.application_result["status"], "skipped")
        self.assertEqual(job.analytics_context, {})
        self.assertEqual(job.reserved_tokens, 0)
        self.assertIsNotNone(job.finished_at)
        self.assertIsNone(job.locked_at)

    def test_queued_delete_releases_budget_without_provider_and_retains_history(self):
        job = self.enqueue()
        self.assertEqual(job.reserved_tokens, 18000)
        deleted = self.delete()
        with patch("portal.processing.process_analysis") as provider:
            self.assertFalse(process_next_job())
        provider.assert_not_called()
        self.assert_cancelled(job)
        self.assertEqual((job.status, job.attempts, job.input_tokens, job.output_tokens), ("failed", 0, 0, 0))
        self.assertEqual(deleted.data, self.machine.data)
        other = Machine.objects.create(owner=self.owner, title="Otro borrador", data={"brand": "Otra marca"})
        self.assertEqual(self.enqueue(other).reserved_tokens, 18000)

    def test_restoring_queued_job_never_restarts_it_but_explicit_new_analysis_can_run(self):
        old = self.enqueue()
        restored = self.delete(restore=True)
        with patch("portal.processing.process_analysis") as provider:
            self.assertFalse(process_next_job())
        provider.assert_not_called()
        self.assert_cancelled(old)
        fresh = self.enqueue(restored)
        self.assertNotEqual(old.pk, fresh.pk)
        self.assertNotEqual(old.fingerprint, fresh.fingerprint)
        self.assertGreater(fresh.revision, old.revision)
        # Missing JSON cancellation keys remain eligible on both supported DBs.
        self.assertEqual(_claim_job().pk, fresh.pk)

    def test_running_success_records_actual_usage_without_applying_deleted_draft(self):
        job = self.enqueue()
        before = deepcopy(self.machine.data)

        def remote_response(_job):
            deleted = self.delete()
            job.refresh_from_db()
            self.assertEqual(job.status, "running")
            self.assertEqual(job.reserved_tokens, 18000)
            self.assertIsNotNone(job.locked_at)
            self.assertIsNotNone(deleted.deleted_at)
            return self.result, self.usage

        with patch("portal.processing.process_analysis", side_effect=remote_response), patch("portal.processing.apply_analysis_automatically") as apply:
            self.assertTrue(process_next_job())
        apply.assert_not_called()
        self.assert_cancelled(job)
        self.assertEqual(job.status, "completed")
        self.assertEqual((job.input_tokens, job.output_tokens), (120, 45))
        current = Machine.all_objects.get(pk=self.machine.pk)
        self.assertEqual(current.data, before)
        self.assertEqual(current.revision, self.machine.revision + 1)
        self.assertFalse(AnalyticsEvent.objects.filter(event="analysis_completed").exists())

    def test_running_delete_restore_still_blocks_completion_and_manual_automatic_replay(self):
        job = self.enqueue()

        def remote_response(_job):
            self.delete(restore=True)
            return self.result, self.usage

        with patch("portal.processing.process_analysis", side_effect=remote_response), patch("portal.processing.apply_analysis_automatically") as apply:
            self.assertTrue(process_next_job())
        apply.assert_not_called()
        self.assert_cancelled(job)
        restored = Machine.objects.get(pk=self.machine.pk)
        self.assertEqual(restored.data, self.machine.data)
        applied, outcome = apply_analysis_automatically(restored, self.owner, job, restored.revision)
        self.assertEqual(outcome["reason"], "draft_deleted")
        self.assertEqual(applied.data, self.machine.data)
        self.assertEqual((job.input_tokens, job.output_tokens), (120, 45))

    def test_deleted_after_claim_is_refused_before_provider_and_charges_zero(self):
        job = self.enqueue()
        claimed = _claim_job()
        self.delete(restore=True)
        with patch("portal.processing._claim_job", return_value=claimed), patch("openai.OpenAI") as provider:
            self.assertTrue(process_next_job())
        provider.assert_not_called()
        self.assert_cancelled(job)
        self.assertEqual(job.status, "failed")
        self.assertEqual((job.input_tokens, job.output_tokens), (0, 0))
        with patch("openai.OpenAI") as provider, self.assertRaises(DraftAnalysisCancelled):
            process_analysis(claimed)
        provider.assert_not_called()

    def test_transient_running_failure_does_not_retry_and_accounts_unknown_remote_cost(self):
        from openai import APIConnectionError
        import httpx2
        job = self.enqueue()

        def interrupted(_job):
            self.delete(restore=True)
            raise APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))

        with patch("portal.processing.process_analysis", side_effect=interrupted) as provider:
            self.assertTrue(process_next_job())
            self.assertFalse(process_next_job())
        self.assertEqual(provider.call_count, 1)
        self.assert_cancelled(job)
        self.assertEqual((job.status, job.attempts), ("failed", 1))
        self.assertEqual((job.input_tokens, job.output_tokens), (9000, 0))

    def test_running_failure_preserves_known_usage_instead_of_full_estimate(self):
        job = self.enqueue()

        def failed_after_usage(_job):
            self.delete()
            failure = ValueError("This provider detail must not be persisted.")
            failure.accounted_usage = self.usage
            raise failure

        with patch("portal.processing.process_analysis", side_effect=failed_after_usage):
            self.assertTrue(process_next_job())
        self.assert_cancelled(job)
        self.assertEqual((job.input_tokens, job.output_tokens), (120, 45))
        self.assertNotIn("provider detail", job.error)

    def test_stale_running_delete_restore_is_terminal_and_conservatively_accounted(self):
        job = self.enqueue()
        _claim_job()
        self.delete(restore=True)
        AnalysisJob.objects.filter(pk=job.pk).update(locked_at=timezone.now() - timedelta(hours=1))
        with patch("openai.OpenAI") as provider:
            self.assertIsNone(_claim_job())
        provider.assert_not_called()
        self.assert_cancelled(job)
        self.assertEqual((job.status, job.attempts, job.input_tokens), ("failed", 1, 9000))

    def test_defensive_cleanup_releases_unmarked_deleted_queue_even_when_ai_paused(self):
        job = self.enqueue()
        # Simulate an old/admin write that did not call the service's hook.
        Machine.all_objects.filter(pk=self.machine.pk).update(deleted_at=timezone.now())
        self.limits.ai_enabled = False
        self.limits.save(update_fields=["ai_enabled"])
        with patch("openai.OpenAI") as provider:
            self.assertIsNone(_claim_job())
        provider.assert_not_called()
        self.assert_cancelled(job)
        self.assertEqual((job.status, job.attempts, job.input_tokens), ("failed", 0, 0))
