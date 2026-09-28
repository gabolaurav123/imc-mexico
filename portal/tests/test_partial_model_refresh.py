"""Retry an existing draft without preserving a disproved automatic model."""
from copy import deepcopy
import uuid

from django.test import TestCase

from portal.models import AnalysisJob, Asset, Category, Consent, Machine, User
from portal.processing import MachineAnalysis, normalize_analysis
from portal.research import empty_research
from portal.services import apply_analysis_automatically, automatic_application_snapshot, save_draft
from portal.tests.test_partial_model_reading import reading


class PartialModelRefreshTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="partial-refresh@example.invalid", is_test=True)
        self.category = Category.objects.create(name="Compactadores", slug="compactadores")
        self.machine = Machine.objects.create(owner=self.owner, category=self.category)
        self.asset = self.photo("a")
        self.previous = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, fingerprint=uuid.uuid4().hex, status="completed",
            result={"data": {"model": "7T-20"}})
        Consent.objects.create(user=self.owner, machine=self.machine, kind="ai", granted=True)
        self.reset_automatic_model()

    def photo(self, digest):
        return Asset.objects.create(machine=self.machine, kind="image", purpose="general", processing_status="ready",
            sha256=digest * 64, size=1, mime_type="image/jpeg", original=f"test/{digest}.jpg")

    def reset_automatic_model(self):
        meta = {"source": "image", "review": "clear", "component": "machine", "asset_id": str(self.asset.pk),
                "analysis_id": str(self.previous.pk)}
        self.machine.title = "Compactador ACME 7T-20"
        self.machine.data = {"brand": "ACME", "model": "7T-20", "description": "Compactador ACME 7T-20."}
        self.machine.provenance = {
            "brand": {**meta, "evidence": "ACME"}, "model": {**meta, "evidence": "7T-20"},
            "title": {"source": "visual_proposal", "review": "needs_review", "analysis_id": str(self.previous.pk)},
            "description": {"source": "system", "review": "needs_review", "analysis_id": str(self.previous.pk)},
        }
        self.machine.save()

    def job(self, asset=None, fragment="7T-20"):
        asset = asset or self.asset
        parsed = reading(f"Inicio del rótulo oculto por la cabina; fragmento «{fragment}».", model=fragment).model_dump()
        for item in parsed["fields"] + parsed["image_observations"]:
            item["asset_id"] = str(asset.pk)
        result = normalize_analysis(MachineAnalysis(**parsed), [str(asset.pk)], allowed_categories=["Compactadores"])
        result["research"] = empty_research("no_results")
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, fingerprint=uuid.uuid4().hex, status="completed", auto_apply=True,
            asset_ids=[str(asset.pk)], application_snapshot=automatic_application_snapshot(self.machine), result=result)

    def apply(self, job):
        self.machine, summary = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        return summary

    def test_retry_retires_exact_old_fragment_and_recomposes_without_losing_history(self):
        job = self.job()
        self.assertIsNone(job.result["data"]["model"])
        summary = self.apply(job)
        self.assertNotIn("model", self.machine.data)
        self.assertNotIn("model", self.machine.provenance)
        self.assertIn("model", summary["invalidated_fields"])
        self.assertEqual(self.machine.title, "Compactador ACME")
        self.assertNotIn("7T-20", self.machine.data["description"])
        self.previous.refresh_from_db()
        self.assertEqual(self.previous.result["data"]["model"], "7T-20")

    def test_human_confirmation_correction_and_clear_survive_before_or_during_retry(self):
        for during in (False, True):
            for model in ("7T-20", "ZX-7T-20", ""):
                with self.subTest(during=during, model=model):
                    self.reset_automatic_model()
                    job = self.job() if during else None
                    self.machine = save_draft(self.machine, self.owner,
                        {"data": {"model": model}, "provenance": {"model": {"source": "user", "review": "confirmed"}}},
                        self.machine.revision)
                    summary = self.apply(job or self.job())
                    self.assertEqual(self.machine.data["model"], model)
                    self.assertEqual(self.machine.provenance["model"]["review"], "confirmed")
                    self.assertNotIn("model", summary.get("invalidated_fields", []))

    def test_newer_automatic_reading_does_not_match_the_retry_snapshot(self):
        job = self.job()
        newer_meta = {**self.machine.provenance["model"], "analysis_id": str(uuid.uuid4())}
        self.machine.provenance["model"] = newer_meta
        self.machine.save()
        summary = self.apply(job)
        self.assertEqual(self.machine.data["model"], "7T-20")
        self.assertEqual(self.machine.provenance["model"], newer_meta)
        self.assertNotIn("model", summary.get("invalidated_fields", []))

    def test_other_photo_or_different_fragment_cannot_disprove_the_old_reading(self):
        for asset, fragment in ((self.photo("b"), "7T-20"), (self.asset, "8X-30")):
            with self.subTest(asset=str(asset.pk), fragment=fragment):
                self.reset_automatic_model()
                old_meta = deepcopy(self.machine.provenance["model"])
                summary = self.apply(self.job(asset=asset, fragment=fragment))
                self.assertEqual(self.machine.data["model"], "7T-20")
                self.assertEqual(self.machine.provenance["model"], old_meta)
                self.assertNotIn("model", summary.get("invalidated_fields", []))
