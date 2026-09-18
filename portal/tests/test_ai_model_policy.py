"""A stronger reasoning model keeps admission, source binding and usage bounded."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from portal.ai_model import (DEFAULT_MODEL, VISION_MODEL, image_model, is_reasoning_model, model_options, output_limit,
                             request_timeout, token_reservation)
from portal.models import AnalysisJob, PlatformSettings
from portal.processing import (DescriptionAnalysis, _claim_job, _job_lease_seconds, _reservation,
                               enqueue_analysis, process_analysis, process_next_job)
from portal.tests import test_image_bindings as fixtures
from portal.tests.test_image_relevance import observation, parsed


class ModelPolicyTests(SimpleTestCase):
    def test_visual_stage_uses_permitted_terra_without_changing_research_model(self):
        self.assertEqual(image_model(DEFAULT_MODEL), VISION_MODEL)
        self.assertEqual(DEFAULT_MODEL, 'gpt-5.6-luna')
        self.assertEqual(image_model('gpt-4.1-mini'), 'gpt-4.1-mini')
        with self.assertRaises(ValueError):
            image_model('gpt-6-astra')

    def test_only_selected_model_and_dated_snapshots_get_reasoning_policy(self):
        self.assertEqual(DEFAULT_MODEL, "gpt-5.6-luna")
        for model in ("gpt-5.6-luna", "gpt-5.6-luna-2026-09-17", "gpt-5.6-terra", "gpt-5.6-terra-2026-09-17"):
            with self.subTest(model=model):
                self.assertTrue(is_reasoning_model(model))
                self.assertEqual(model_options(model), {"reasoning": {"effort": "low"}})
                self.assertEqual(output_limit(model, 4500), 8000)
                self.assertEqual(token_reservation(model, 12200), 15700)
                self.assertEqual(request_timeout(model, 45), 120)
                self.assertEqual(request_timeout(model, 180), 180)
        for model in ("gpt-4.1-mini", "gpt-4.1", "gpt-5.6-luna-mini", "gpt-5.6-luna-pro",
                      "gpt-5.6-lunaish", "GPT-6-LUNA", "", None):
            with self.subTest(legacy_or_other=model):
                self.assertFalse(is_reasoning_model(model))
                self.assertEqual(model_options(model), {})
                self.assertEqual(output_limit(model, 4500), 4500)
                self.assertEqual(token_reservation(model, 12200), 12200)
                self.assertEqual(request_timeout(model, 90), 90)

    def test_astra_is_blocked_even_if_an_old_configuration_selects_it(self):
        for model in ("gpt-6-astra", "gpt-6-astra-2026-09-17", "gpt-6-astra-pro"):
            with self.subTest(model=model), self.assertRaisesRegex(ValueError, "deshabilitado"):
                model_options(model)

    def test_reservation_adds_reasoning_for_each_actual_pipeline_request(self):
        for images in (0, 1, 2, 20):
            with self.subTest(images=images):
                self.assertEqual(_reservation(images, "analysis", model=DEFAULT_MODEL), max(1, images) * 15700)
                self.assertEqual(_reservation(images, "analysis", True, model=DEFAULT_MODEL), max(1, images) * 15700 + 95500 + 43000)
                self.assertEqual(_reservation(images, "analysis", True, model="gpt-4.1-mini"), max(1, images) * 12200 + 78000 + 36000)
        self.assertEqual(_reservation(0, "description", model=DEFAULT_MODEL), 12500)
        self.assertEqual(_reservation(0, "description", True, model=DEFAULT_MODEL, research_description_only=True), 95500)

    @override_settings(OPENAI_TIMEOUT=90, AI_JOB_STALE_SECONDS=600)
    def test_lease_covers_serial_vision_research_valuation_and_preserves_recorded_deadline(self):
        for count in (1, 20):
            with self.subTest(images=count):
                job = SimpleNamespace(model=DEFAULT_MODEL, mode="analysis", asset_ids=["photo"] * count,
                    result={"research_requested": True})
                self.assertGreaterEqual(_job_lease_seconds(job), count * 120 + 900)
                job.result["execution_lease_seconds"] = 5000
                self.assertEqual(_job_lease_seconds(job), 5000)
        legacy = SimpleNamespace(model="gpt-4.1-mini", mode="analysis", asset_ids=["photo"], result={})
        self.assertEqual(_job_lease_seconds(legacy), 600)


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-5.6-luna",
                   OPENAI_TIMEOUT=90, AI_JOB_STALE_SECONDS=600)
class ReasoningModelWorkerTests(TestCase):
    def setUp(self):
        fixtures.ImageMessageBindingTests.setUp(self)
        self.enterContext(patch("portal.processing._image_input",
            return_value={"type": "input_image", "image_url": "data:synthetic-photo"}))
        self.provider = self.enterContext(patch("openai.OpenAI"))

    def photo(self, *, model="gpt-5.6-terra-2026-09-17", usage=True):
        return SimpleNamespace(status="completed", model=model,
            output_parsed=parsed([observation("image_001", category="Montacargas")]),
            usage=SimpleNamespace(input_tokens=1000, output_tokens=5000,
                output_tokens_details=SimpleNamespace(reasoning_tokens=4500)) if usage else None)

    def test_astra_cannot_be_queued_or_dispatched_from_a_historical_job(self):
        with override_settings(OPENAI_MODEL="gpt-6-astra"), self.assertRaises(ValidationError):
            enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        self.assertFalse(AnalysisJob.objects.exists())
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        AnalysisJob.objects.filter(pk=job.pk).update(model="gpt-6-astra")
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertEqual((job.input_tokens, job.output_tokens, job.reserved_tokens), (0, 0, 0))
        self.provider.assert_not_called()

    def test_enqueued_model_is_pinned_across_environment_changes_and_reasoning_is_not_double_counted(self):
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        self.assertEqual(job.model, DEFAULT_MODEL)
        self.assertEqual(job.result['vision_model'], VISION_MODEL)
        self.assertEqual(job.result["reservation_per_attempt"], 31400)
        self.provider.return_value.responses.parse.side_effect = [self.photo(), self.photo()]
        with override_settings(OPENAI_MODEL="gpt-4.1-mini"):
            self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual((job.input_tokens, job.output_tokens), (2000, 10000))
        for call in self.provider.return_value.responses.parse.call_args_list:
            self.assertEqual(call.kwargs["model"], VISION_MODEL)
            self.assertEqual(call.kwargs["reasoning"], {"effort": "low"})
            self.assertEqual(call.kwargs["max_output_tokens"], 8000)
            self.assertFalse(call.kwargs["store"])
        self.assertEqual(self.provider.call_args.kwargs["timeout"], 120)
        self.assertEqual([r["provider_model"] for r in job.result["image_readings"]],
                         ["gpt-5.6-terra-2026-09-17"] * 2)
        self.assertEqual([r['requested_model'] for r in job.result['image_readings']], [VISION_MODEL] * 2)

    def test_historical_luna_job_without_stage_policy_still_dispatches_luna(self):
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        job.result.pop('vision_model')
        job.save(update_fields=['result'])
        self.provider.return_value.responses.parse.side_effect = [self.photo(model=DEFAULT_MODEL), self.photo(model=DEFAULT_MODEL)]
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        self.assertEqual([c.kwargs['model'] for c in self.provider.return_value.responses.parse.call_args_list], [DEFAULT_MODEL] * 2)

    def test_exact_capacity_admits_one_attempt_but_one_token_short_never_calls_provider(self):
        limits = PlatformSettings.objects.get(pk=1)
        limits.ai_daily_token_limit = 2 * 15700 + 95500 + 43000 - 1
        limits.save()
        with self.assertRaises(ValidationError):
            enqueue_analysis(self.machine, self.owner, authorize_ai=True, research=True)
        self.provider.assert_not_called()
        self.assertFalse(AnalysisJob.objects.exists())
        limits.ai_daily_token_limit += 1
        limits.save()
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True, research=True)
        self.assertEqual((job.reserved_tokens, job.result["attempt_limit"]), (169900, 1))
        limits.refresh_from_db()
        self.assertEqual(limits.ai_daily_token_limit, 169900)

    def test_missing_usage_and_second_photo_timeout_charge_only_attempted_reasoning_requests(self):
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        self.provider.return_value.responses.parse.side_effect = [self.photo(usage=False), TimeoutError()]
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.result["image_analysis_status"], "partial")
        self.assertEqual(job.result["usage"]["estimated_tokens"], 31400)
        self.assertEqual(job.input_tokens + job.output_tokens, 31400)
        self.assertEqual([r["status"] for r in job.result["image_readings"]], ["completed", "failed"])

    def test_description_uses_policy_and_only_keeps_safe_provider_model_metadata(self):
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True, mode="description")
        self.provider.return_value.responses.parse.return_value = SimpleNamespace(status="completed",
            model="gpt-5.6-luna-2026-09-17", output_parsed=DescriptionAnalysis(description="Equipo declarado.", warnings=[], questions=[]),
            usage=SimpleNamespace(input_tokens=100, output_tokens=500))
        result, _ = process_analysis(job)
        self.assertEqual(result["provider_model"], "gpt-5.6-luna-2026-09-17")
        self.assertEqual(self.provider.return_value.responses.parse.call_args.kwargs["reasoning"], {"effort": "low"})
        self.assertEqual(job.result["reservation_per_attempt"], 12500)
        self.provider.return_value.responses.parse.return_value.model = "https://unsafe.example/private"
        result, _ = process_analysis(job)
        self.assertNotIn("provider_model", result)
        self.provider.return_value.responses.parse.return_value.usage = None
        result, usage = process_analysis(job)
        self.assertEqual(usage.estimated_tokens, 12500)
        self.assertEqual(result["usage"]["input_tokens"], 12500)

    def test_incomplete_reasoning_response_retains_consumption_without_model_fallback(self):
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        self.provider.return_value.responses.parse.return_value = SimpleNamespace(status="incomplete", output_parsed=None,
            model=DEFAULT_MODEL, usage=SimpleNamespace(input_tokens=1000, output_tokens=8000,
                output_tokens_details=SimpleNamespace(reasoning_tokens=7900)))
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertEqual((job.input_tokens, job.output_tokens, job.reserved_tokens), (1000, 8000, 0))
        self.assertEqual(self.provider.return_value.responses.parse.call_count, 1)
        self.assertEqual(self.provider.return_value.responses.parse.call_args.kwargs["model"], VISION_MODEL)

    def test_legacy_job_keeps_legacy_requests_after_global_upgrade(self):
        with override_settings(OPENAI_MODEL="gpt-4.1-mini"):
            job = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        self.provider.return_value.responses.parse.side_effect = [self.photo(model="gpt-4.1-mini"), self.photo(model="gpt-4.1-mini")]
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.model, "gpt-4.1-mini")
        self.assertEqual(job.result["reservation_per_attempt"], 24400)
        for call in self.provider.return_value.responses.parse.call_args_list:
            self.assertEqual(call.kwargs["model"], "gpt-4.1-mini")
            self.assertNotIn("reasoning", call.kwargs)
            self.assertEqual(call.kwargs["max_output_tokens"], 4500)

    def test_model_change_creates_new_job_instead_of_reusing_old_fingerprint(self):
        with override_settings(OPENAI_MODEL="gpt-4.1-mini"):
            older = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        newer = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        self.assertNotEqual(newer.pk, older.pk)
        self.assertNotEqual(newer.fingerprint, older.fingerprint)

    def test_long_reasoning_job_is_not_reclaimed_under_legacy_deadline(self):
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True, research=True)
        claimed = _claim_job()
        self.assertEqual(claimed.pk, job.pk)
        original = timezone.now() - timedelta(seconds=900)
        AnalysisJob.objects.filter(pk=job.pk).update(locked_at=original)
        self.assertIsNone(_claim_job())
        job.refresh_from_db()
        self.assertEqual(job.locked_at, original)
        self.assertEqual(job.attempts, 1)
