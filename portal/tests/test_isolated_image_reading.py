"""Independent photo calls preserve facts, partial usage and consent boundaries."""
from types import SimpleNamespace
from unittest.mock import patch

import httpx2
from openai import APIConnectionError
from django.test import SimpleTestCase, TestCase, override_settings

from portal.models import Asset, Consent, PlatformSettings
from portal.processing import (_merge_image_results, normalize_analysis, enqueue_analysis,
                               process_next_job, IMAGE_RESERVATION)
from portal.tests.test_image_relevance import field, observation, parsed
from portal.tests import test_image_bindings as binding_fixtures

PLATE_ID = binding_fixtures.PLATE_ID


def normalized(asset, fields=(), *, kind="machine", relevance="machinery", transcript=None):
    plates = [dict(asset_id=asset, component="machine", readability="clear", transcription=transcript)] if transcript else []
    return normalize_analysis(parsed([observation(asset, relevance, kind, category="Montacargas")], fields, plates),
                              [asset], allowed_categories=["Montacargas"])


class IsolatedImageMergeTests(SimpleTestCase):
    def test_empty_general_photo_fields_cannot_erase_plate_manufacturer(self):
        plate = normalized("plate", [field("manufacturer", "EXAMPLE MACHINERY CO.", "plate", "plate"),
            field("manufacturer_address", "Example City", "plate", "plate")], kind="plate", relevance="related",
            transcript="EXAMPLE MACHINERY CO. Example City")
        general = normalized("general", [field("manufacturer", None, "general"),
                                         field("manufacturer_address", None, "general")])
        for readings, ids in (([plate, general], ["plate", "general"]), ([general, plate], ["general", "plate"])):
            with self.subTest(ids=ids):
                result = _merge_image_results(readings, ids, ["Montacargas"])
                self.assertEqual(result["data"]["manufacturer"], "EXAMPLE MACHINERY CO.")
                self.assertEqual(result["data"]["manufacturer_address"], "Example City")
                self.assertEqual(result["provenance"]["manufacturer"]["asset_id"], "plate")

    def test_equal_readings_deduplicate_without_promoting_uncertainty(self):
        unclear = field("power", "10 kW", "a")
        unclear["review"] = "needs_review"
        first = normalized("a", [unclear])
        second = normalized("b", [field("power", "10 kW", "b")])
        result = _merge_image_results([first, second], ["a", "b"], ["Montacargas"])
        self.assertEqual(result["data"]["power"], "10 kW")
        self.assertEqual(result["provenance"]["power"]["asset_id"], "b")
        self.assertEqual(result["provenance"]["power"]["review"], "clear")
        unclear_b = field("power", "10 kW", "b")
        unclear_b["review"] = "needs_review"
        result = _merge_image_results([first, normalized("b", [unclear_b])], ["a", "b"], ["Montacargas"])
        self.assertEqual(result["provenance"]["power"]["review"], "needs_review")

    def test_conflicting_nonempty_values_remain_pending_regardless_of_photo_order(self):
        first = normalized("a", [field("power", "10 kW", "a")])
        second = normalized("b", [field("power", "20 kW", "b")])
        for readings in ([first, second], [second, first]):
            with self.subTest(order=readings[0]["fields"][0]["asset_id"]):
                result = _merge_image_results(readings, ["a", "b"], ["Montacargas"])
                self.assertIsNone(result["data"]["power"])
                self.assertEqual(result["provenance"]["power"]["review"], "needs_review")
                self.assertNotIn("10 kW", result["description"])
                self.assertNotIn("20 kW", result["description"])

    def test_twenty_bounded_plate_transcriptions_do_not_hit_single_response_size_limit(self):
        ids = [f"photo-{index}" for index in range(20)]
        readings = [normalized(asset, [field("brand", "EXAMPLE", asset, "plate")],
            kind="plate", relevance="related", transcript="EXAMPLE " + "Lectura técnica. " * 500) for asset in ids]
        result = _merge_image_results(readings, ids, ["Montacargas"])
        self.assertEqual(result["data"]["brand"], "EXAMPLE")
        self.assertEqual(len(result["fields"]), 1)
        self.assertEqual(len(result["plates"]), 20)
        self.assertTrue(all(plate["transcription"].endswith("Lectura técnica. ") for plate in result["plates"]))


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-4.1-mini")
class IsolatedImageWorkerTests(TestCase):
    def setUp(self):
        binding_fixtures.ImageMessageBindingTests.setUp(self)

    def good(self):
        return SimpleNamespace(status="completed", output_parsed=parsed(
            [observation("image_001", "related", "plate", category="Montacargas")],
            [field("manufacturer", "EXAMPLE CO.", "image_001", "plate")],
            [dict(asset_id="image_001", component="machine", readability="clear", transcription="EXAMPLE CO.")]),
            usage=SimpleNamespace(input_tokens=400, output_tokens=200))

    def queue(self, research=True):
        return enqueue_analysis(self.machine, self.owner, authorize_ai=True, research=research)

    def third(self):
        return Asset.objects.create(id="00000000-0000-0000-0000-000000000002", machine=self.machine,
            kind="image", purpose="general", processing_status="ready", original="test/third.jpg", preview="test/third.jpg",
            size=1, mime_type="image/jpeg", sha256="c" * 64, position=2)

    def test_later_timeout_keeps_good_reading_estimates_only_failed_call_and_skips_remaining_and_research(self):
        self.third()
        job = self.queue()
        failure = APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))
        with patch("portal.processing._image_input", return_value={"type": "input_image", "image_url": "data:test"}), \
             patch("openai.OpenAI") as provider, patch("portal.processing.research_machine") as research:
            provider.return_value.responses.parse.side_effect = [self.good(), failure]
            self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.assertEqual(provider.return_value.responses.parse.call_count, 2)
        research.assert_not_called()
        self.assertEqual((job.status, job.input_tokens, job.output_tokens, job.reserved_tokens),
                         ("completed", 400 + IMAGE_RESERVATION, 200, 0))
        self.assertEqual(job.result["data"]["manufacturer"], "EXAMPLE CO.")
        self.assertEqual(job.result["provenance"]["manufacturer"]["asset_id"], PLATE_ID)
        self.assertEqual([item["status"] for item in job.result["image_readings"]], ["completed", "failed", "not_run"])
        self.assertEqual(job.result["usage"]["estimated_tokens"], IMAGE_RESERVATION)
        self.assertEqual(job.result["image_analysis_status"], "partial")
        self.assertFalse(job.result["image_analysis_complete"])
        self.assertIn("interrumpió", job.result["relevance"]["message"])

    def test_first_remote_failure_uses_existing_retry_and_does_not_claim_blurry_images(self):
        job = self.queue()
        failure = APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))
        with patch("portal.processing._image_input", return_value={"type": "input_image", "image_url": "data:test"}), \
             patch("openai.OpenAI") as provider:
            provider.return_value.responses.parse.side_effect = failure
            self.assertTrue(process_next_job())
        job.refresh_from_db()
        provider.return_value.responses.parse.assert_called_once()
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.input_tokens, IMAGE_RESERVATION)
        self.assertEqual(job.reserved_tokens, job.result["reservation_per_attempt"])
        self.assertNotIn("relevance", job.result)

    def test_revocation_after_first_read_prevents_next_image_and_preserves_measured_usage(self):
        job = self.queue()
        def first(**kwargs):
            Consent.objects.create(user=self.owner, machine=self.machine, kind="ai", granted=False)
            return self.good()
        with patch("portal.processing._image_input", return_value={"type": "input_image", "image_url": "data:test"}), \
             patch("openai.OpenAI") as provider, patch("portal.processing.research_machine") as research:
            provider.return_value.responses.parse.side_effect = first
            self.assertTrue(process_next_job())
        job.refresh_from_db()
        provider.return_value.responses.parse.assert_called_once()
        research.assert_not_called()
        self.assertEqual((job.status, job.input_tokens, job.output_tokens, job.reserved_tokens), ("failed", 400, 200, 0))

    def test_lowered_global_budget_stops_before_next_call_without_spending_or_estimating_unattempted_photo(self):
        job = self.queue()
        def first(**kwargs):
            PlatformSettings.objects.filter(pk=1).update(ai_daily_token_limit=600)
            return self.good()
        with patch("portal.processing._image_input", return_value={"type": "input_image", "image_url": "data:test"}), \
             patch("openai.OpenAI") as provider, patch("portal.processing.research_machine") as research:
            provider.return_value.responses.parse.side_effect = first
            self.assertTrue(process_next_job())
        job.refresh_from_db()
        provider.return_value.responses.parse.assert_called_once()
        research.assert_not_called()
        self.assertEqual((job.input_tokens, job.output_tokens, job.reserved_tokens), (400, 200, 0))
        self.assertEqual(job.result["usage"]["estimated_tokens"], 0)
        self.assertEqual([item["status"] for item in job.result["image_readings"]], ["completed", "budget_unavailable"])
        self.assertEqual(job.result["data"]["manufacturer"], "EXAMPLE CO.")
