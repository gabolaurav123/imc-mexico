"""Explicit retries reread unsupported visual models without changing budgets."""
from copy import deepcopy
from uuid import uuid4

from django.test import TestCase

from portal.models import AnalysisJob, Asset, Machine, User
from portal.processing import PROMPT_VERSION, _cached_photo_readings, _photo_cache_keys
from portal.tests.test_research import IDENTITY, normalized, vision


class PhotoCacheIdentityRetryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="cache-identity@example.invalid")
        self.machine = Machine.objects.create(owner=self.user)
        self.asset = Asset.objects.create(machine=self.machine, kind="image", purpose="general",
            processing_status="ready", sha256="a" * 64, original="test/cache.jpg", size=1, mime_type="image/jpeg")
        self.job = self.make_job(status="running")
        self.keys = _photo_cache_keys(self.job, [self.asset], {})
        self.key = self.keys[str(self.asset.pk)]

    def make_job(self, **changes):
        values = dict(machine=self.machine, requested_by=self.user, revision=self.machine.revision,
            asset_ids=[str(self.asset.pk)], mode="analysis", fingerprint=uuid4().hex,
            prompt_version=PROMPT_VERSION, model="gpt-6-luna", status="completed")
        return AnalysisJob.objects.create(**{**values, **changes})

    def prior(self, **changes):
        reading = vision(asset=str(self.asset.pk))
        reading["relevance"] = {"status": "relevant", "accepted_asset_ids": [str(self.asset.pk)]}
        result = {"research_requested": True, "input_snapshot": {},
            "completion": {"missing_fields": ["year_range", "price_range", "description"]},
            "research": {"status": "no_results", "identity": deepcopy(IDENTITY), "fields": []},
            "photo_cache": [{"key": self.key, "asset_id": str(self.asset.pk), "sha256": self.asset.sha256,
                "purpose": "general", "reading": reading}]}
        result.update(changes)
        return self.make_job(result=result)

    def test_incomplete_lookup_cannot_reuse_same_reading_or_older_preflight(self):
        older = self.prior(preflight=True, research_requested=False, completion={})
        latest = self.prior()
        before = deepcopy(latest.result)
        self.assertEqual(_cached_photo_readings(self.job, self.keys), {})
        older.refresh_from_db()
        latest.refresh_from_db()
        self.assertEqual(latest.result, before)
        self.assertTrue(older.result["photo_cache"])
        self.assertEqual(AnalysisJob.objects.count(), 3)

    def test_initial_preflight_and_complete_sheets_still_reuse_reading(self):
        for changes in ({"preflight": True, "research_requested": False, "completion": {}},
                        {"completion": {"missing_fields": []}},
                        {"completion": {"missing_fields": ["description"]}},
                        {"research_requested": False}):
            with self.subTest(changes=changes):
                prior = self.prior(**changes)
                self.assertIn(self.key, _cached_photo_readings(self.job, self.keys))
                prior.delete()

    def test_provider_failure_or_unfunded_research_does_not_repeat_valid_ocr(self):
        for status in ("degraded", "not_run", "disabled"):
            with self.subTest(status=status):
                prior = self.prior(research={"status": status, "fields": []})
                self.assertIn(self.key, _cached_photo_readings(self.job, self.keys))
                prior.delete()

    def test_signed_document_can_corroborate_model_even_with_missing_market_range(self):
        prior = self.prior(research=normalized())
        self.assertTrue(prior.result["research"]["fields"])
        self.assertIn(self.key, _cached_photo_readings(self.job, self.keys))
        original = deepcopy(prior.result)
        for modification in ("unsigned", "different_model", "different_brand"):
            with self.subTest(modification=modification):
                result = deepcopy(original)
                if modification == "unsigned":
                    result["research"].pop("proof")
                elif modification == "different_model":
                    result["photo_cache"][0]["reading"]["data"]["model"] = "OTHER-42"
                else:
                    result["photo_cache"][0]["reading"]["data"]["brand"] = "OTHER"
                prior.result = result
                prior.save(update_fields=["result"])
                self.assertEqual(_cached_photo_readings(self.job, self.keys), {})

    def test_unresolved_partial_model_is_read_again_after_an_incomplete_lookup(self):
        prior = self.prior(completion={"missing_fields": ["model", "year_range", "price_range"]})
        reading = prior.result["photo_cache"][0]["reading"]
        reading["data"]["model"] = None
        reading["provenance"]["model"]["review"] = "needs_review"
        prior.save(update_fields=["result"])
        self.assertEqual(_cached_photo_readings(self.job, self.keys), {})

    def test_plate_and_owner_declared_models_keep_their_existing_cache_policy(self):
        for kind in ("plate", "human", "confirmed"):
            with self.subTest(kind=kind):
                prior = self.prior()
                if kind == "plate":
                    prior.result["photo_cache"][0]["purpose"] = "plate"
                    prior.result["photo_cache"][0]["reading"]["provenance"]["model"]["source"] = "plate"
                else:
                    prior.result["input_snapshot"] = {"data": {"model": "OWNER-42"},
                        "provenance": {"model": {"source": "user"} if kind == "human" else
                                                 {"source": "image", "review": "confirmed"}}}
                prior.save(update_fields=["result"])
                self.assertIn(self.key, _cached_photo_readings(self.job, self.keys))
                prior.delete()

    def test_newer_completed_reading_wins_over_an_older_incomplete_attempt(self):
        self.prior()
        newest = self.prior(completion={"missing_fields": []})
        newest.result["photo_cache"][0]["reading"]["data"]["description"] = "Newer result"
        newest.save(update_fields=["result"])
        self.assertEqual(_cached_photo_readings(self.job, self.keys)[self.key]["data"]["description"], "Newer result")
