"""Optional commercial research shares the queue's limits and consent boundary."""
from types import SimpleNamespace
from unittest.mock import patch

import httpx2
from openai import APIConnectionError
from django.test import TestCase, override_settings

from portal.models import Consent, PlatformSettings
from portal.processing import IMAGE_RESERVATION, _reservation, enqueue_analysis, process_next_job
from portal.research import RESEARCH_RESERVATION, UsageTotals, empty_research
from portal.services import save_draft
from portal.tests import test_image_bindings as fixtures
from portal.tests.test_image_relevance import field, observation, parsed
from portal.valuation import LABEL, VALUATION_RESERVATION, VALUATION_VERSION, _seal


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-4.1-mini")
class ValuationPipelineTests(TestCase):
    def setUp(self):
        fixtures.ImageMessageBindingTests.setUp(self)
        self.machine.data = {"brand": "Caterpillar", "model": "2EC25", "condition": "Usada"}
        self.machine.provenance = {key: {"source": "user", "review": "confirmed"} for key in self.machine.data}
        self.machine.save()
        self.provider = self.enterContext(patch("openai.OpenAI"))
        self.enterContext(patch("portal.processing._image_input", return_value={"type": "input_image", "image_url": "data:test"}))
        self.research = self.enterContext(patch("portal.processing.research_machine",
            return_value=(empty_research("no_results"), UsageTotals())))
        self.estimate = self.enterContext(patch("portal.processing.estimate_machine",
            return_value=(self.valuation(), UsageTotals())))

    @staticmethod
    def valuation():
        return _seal({"version": VALUATION_VERSION, "label": LABEL, "status": "estimated",
            "identity": {"brand": "Caterpillar", "model": "2EC25", "condition": "used", "configurations": {}},
            "fields": {"estimate_min": "10000", "estimate_max": "20000", "estimate_currency": "USD",
                       "estimate_market": "Estados Unidos", "estimate_basis": "Comparables públicos",
                       "estimate_missing_info": "Confirmar funcionamiento"},
            "suggested_price": "15000", "comparables": []})

    @staticmethod
    def photo(relevance="machinery", kind="machine"):
        return SimpleNamespace(status="completed", output_parsed=parsed(
            [observation("image_001", relevance, kind, category="Montacargas")],
            [field("brand", "Caterpillar", "image_001"), field("model", "2EC25", "image_001")]),
            usage=SimpleNamespace(input_tokens=400, output_tokens=200))

    def queue(self, *, research=True, mode="analysis", auto_apply=False):
        return enqueue_analysis(self.machine, self.owner, research=research, authorize_ai=True,
            mode=mode, auto_apply=auto_apply, expected_revision=self.machine.revision if auto_apply else None)

    def test_reservation_adds_one_valuation_to_image_analysis_only(self):
        for count in (1, 2, 20):
            with self.subTest(count=count):
                self.assertEqual(_reservation(count, "analysis", True),
                    count * IMAGE_RESERVATION + RESEARCH_RESERVATION + VALUATION_RESERVATION)
                self.assertEqual(_reservation(count, "analysis", False), count * IMAGE_RESERVATION)
        self.assertEqual(_reservation(0, "description", True, research_description_only=True), RESEARCH_RESERVATION)
        job = self.queue()
        self.assertEqual(job.result["reservation_per_attempt"], 2 * IMAGE_RESERVATION + RESEARCH_RESERVATION + VALUATION_RESERVATION)

    def test_complete_readings_run_one_valuation_and_account_all_usage(self):
        self.provider.return_value.responses.parse.side_effect = [self.photo(), self.photo()]
        self.research.return_value = (empty_research("no_results"), UsageTotals(1200, 150, 400, 1))
        self.estimate.return_value = (self.valuation(), UsageTotals(2300, 350, 800, 1))
        job = self.queue(auto_apply=True)
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.estimate.assert_called_once()
        self.assertEqual(self.provider.return_value.responses.parse.call_count, 2)
        self.provider.return_value.responses.create.assert_not_called()
        self.assertEqual((job.input_tokens, job.output_tokens, job.reserved_tokens), (4300, 900, 0))
        self.assertEqual(job.result["usage"]["estimated_tokens"], 1200)
        self.assertEqual(job.result["usage"]["web_search_calls"], 2)
        self.assertEqual(self.machine.data["price"], "15000")
        self.assertEqual(self.machine.data["currency"], "USD")
        self.assertEqual(self.machine.provenance["price"]["source"], "valuation")

    def test_ocr_only_and_description_research_do_not_call_valuation(self):
        self.provider.return_value.responses.parse.side_effect = [self.photo(), self.photo()]
        first = self.queue(research=False)
        self.assertTrue(process_next_job())
        first.refresh_from_db()
        self.estimate.assert_not_called()
        second = self.queue(mode="description")
        self.assertTrue(process_next_job())
        second.refresh_from_db()
        self.estimate.assert_not_called()
        self.assertEqual(second.status, "completed")
        self.assertNotIn("valuation", second.result)
        self.assertEqual(self.provider.return_value.responses.parse.call_count, 2)

    def test_unrelated_photos_never_trigger_research_or_valuation_despite_declared_identity(self):
        self.provider.return_value.responses.parse.side_effect = [self.photo("unrelated", "other"), self.photo("unrelated", "other")]
        job = self.queue()
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.research.assert_not_called()
        self.estimate.assert_not_called()
        self.assertEqual(job.result["data"], {})
        self.assertEqual((job.input_tokens, job.output_tokens), (800, 400))

    def test_partial_image_pipeline_never_estimates_price(self):
        failure = APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))
        self.provider.return_value.responses.parse.side_effect = [self.photo(), failure]
        job = self.queue()
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.estimate.assert_not_called()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.result["valuation"], {"status": "not_run", "reason": "image_pipeline_incomplete"})
        self.assertNotIn("price", job.result["data"])
        self.assertEqual((job.input_tokens, job.output_tokens), (400 + IMAGE_RESERVATION, 200))

    def test_owner_price_edited_during_provider_call_wins_while_snapshot_stays_original(self):
        self.provider.return_value.responses.parse.side_effect = [self.photo(), self.photo()]
        def estimate(client, model, result, input_snapshot, **kwargs):
            self.assertEqual(input_snapshot["data"]["model"], "2EC25")
            self.assertEqual(input_snapshot["provenance"]["model"]["review"], "confirmed")
            self.assertTrue(kwargs["allowed"]())
            self.machine = save_draft(self.machine, self.owner,
                {"data": {"price": "7777", "currency": "MXN"}}, self.machine.revision)
            return self.valuation(), UsageTotals(300, 100)
        self.estimate.side_effect = estimate
        job = self.queue(auto_apply=True)
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(self.machine.data["price"], "7777")
        self.assertEqual(self.machine.data["currency"], "MXN")
        self.assertEqual(self.machine.provenance["price"], {"source": "user", "review": "confirmed"})

    def test_valuation_authorization_rechecks_consent_before_external_work(self):
        self.provider.return_value.responses.parse.side_effect = [self.photo(), self.photo()]
        observed = []
        def estimate(client, model, result, input_snapshot, **kwargs):
            self.assertTrue(kwargs["allowed"]())
            Consent.objects.create(user=self.owner, machine=self.machine, kind="ai", granted=False)
            self.assertFalse(kwargs["allowed"]())
            observed.append("revoked")
            return {"status": "not_run", "fields": {}, "comparables": []}, UsageTotals()
        self.estimate.side_effect = estimate
        job = self.queue(auto_apply=True)
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual(observed, ["revoked"])
        self.assertEqual((job.input_tokens, job.output_tokens), (800, 400))
        self.assertNotIn("price", self.machine.data)
        self.assertEqual(job.application_result["reason"], "consent_revoked")

    def test_valuation_is_skipped_when_current_global_capacity_cannot_cover_its_reserve(self):
        self.provider.return_value.responses.parse.side_effect = [self.photo(), self.photo()]
        def research(*args, **kwargs):
            PlatformSettings.objects.filter(pk=1).update(ai_daily_token_limit=1200)
            return empty_research("no_results"), UsageTotals()
        self.research.side_effect = research
        job = self.queue()
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.estimate.assert_not_called()
        self.assertEqual(job.result["valuation"], {"status": "not_run", "reason": "budget_unavailable"})
        self.assertEqual((job.input_tokens, job.output_tokens), (800, 400))
