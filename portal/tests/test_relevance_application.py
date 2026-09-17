"""Image suitability is enforced at both saved-analysis application boundaries."""
from copy import deepcopy
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import TestCase

from portal.models import AnalysisJob, Asset, Category, Consent, Machine, User
from portal.services import (apply_analysis_automatically, apply_analysis_suggestions,
                             automatic_application_snapshot, save_draft)


class RelevanceApplicationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="relevance-application@example.invalid", is_test=True)
        self.category = Category.objects.create(name="Montacargas", slug="montacargas")
        self.machine = Machine.objects.create(owner=self.owner)
        self.good = Asset.objects.create(machine=self.machine, kind="image", processing_status="ready", sha256="a" * 64)
        self.bad = Asset.objects.create(machine=self.machine, kind="image", processing_status="ready", sha256="b" * 64)
        Consent.objects.create(machine=self.machine, user=self.owner, kind="ai", granted=True)

    def job(self, status, **kwargs):
        good_meta = {"source": "image", "review": "clear", "component": "machine", "asset_id": str(self.good.pk), "evidence": "CAT"}
        result = {"data": {"title": "Montacargas CAT", "brand": "CAT", "model": "AJENO", "description": "Una propuesta que no debe aplicarse."},
            "category": "Montacargas", "fields": [], "plates": [],
            "provenance": {"title": {"source": "visual_proposal", "review": "needs_review"},
                "description": {"source": "system", "review": "needs_review"}, "brand": good_meta,
                "model": {**good_meta, "asset_id": str(self.bad.pk), "evidence": "AJENO"}},
            "relevance": {"status": status, "accepted_asset_ids": [str(self.good.pk)],
                "excluded_asset_ids": [str(self.bad.pk)], "uncertain_asset_ids": []}}
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, asset_ids=[str(self.good.pk), str(self.bad.pk)],
            fingerprint=uuid4().hex, status="completed", auto_apply=True,
            application_snapshot=automatic_application_snapshot(self.machine), result=result, **kwargs)

    def test_unrelated_or_uncertain_result_cannot_mutate_existing_draft_in_worker_or_browser(self):
        self.machine = save_draft(self.machine, self.owner, {"title": "Mi equipo revisado", "category": self.category.pk,
            "data": {"brand": "Marca declarada", "description": "Descripción conservada", "location": "Patio"}}, self.machine.revision)
        original = (self.machine.title, self.machine.category_id, deepcopy(self.machine.data),
                    deepcopy(self.machine.provenance), self.machine.revision)
        for status in ("unrelated", "uncertain"):
            for worker in (False, True):
                with self.subTest(status=status, worker=worker):
                    job = self.job(status)
                    machine, result = apply_analysis_automatically(self.machine, self.owner, job,
                        self.machine.revision, from_worker=worker)
                    self.assertEqual(result["status"], "skipped")
                    self.assertEqual(result["reason"], "images_" + status)
                    self.assertEqual(result["applied_fields"], [])
                    self.assertEqual((machine.title, machine.category_id, machine.data, machine.provenance, machine.revision), original)
                    self.assertEqual(machine.assets.count(), 2)

    def test_manual_suggestion_endpoint_cannot_bypass_no_machinery_result(self):
        self.client.force_login(self.owner)
        for status in ("unrelated", "uncertain"):
            job = self.job(status)
            response = self.client.post(f"/api/maquinarias/{self.machine.pk}/aplicar/", {
                "job_id": str(job.pk), "fields": ["brand"], "revision": self.machine.revision}, content_type="application/json")
            self.assertEqual(response.status_code, 400)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.data, {})

    def test_mixed_analysis_applies_good_field_but_not_excluded_image_field(self):
        job = self.job("mixed")
        machine, result = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        self.assertEqual(machine.data["brand"], "CAT")
        self.assertNotIn("model", machine.data)
        self.assertIn("model", result["skipped_fields"])
        self.assertEqual(machine.assets.count(), 2)

    def test_manual_selection_of_mixed_excluded_or_uncertain_asset_is_rejected_atomically(self):
        for key in ("excluded_asset_ids", "uncertain_asset_ids"):
            with self.subTest(key=key):
                job = self.job("mixed")
                job.result["relevance"]["excluded_asset_ids"] = []
                job.result["relevance"][key] = [str(self.bad.pk)]
                job.save()
                with self.assertRaises(ValidationError):
                    apply_analysis_suggestions(self.machine, self.owner, job, ["brand", "model"], self.machine.revision)
                self.machine.refresh_from_db()
                self.assertEqual(self.machine.data, {})

    def test_description_mode_and_legacy_analyses_do_not_acquire_photo_rejections(self):
        for mode, status in (("description", "unrelated"), ("analysis", "unassessed")):
            with self.subTest(mode=mode):
                job = self.job(status, mode=mode)
                job.result["relevance"]["excluded_asset_ids"] = []
                job.save()
                machine, result = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
                self.assertNotIn(result["reason"], {"images_unrelated", "images_uncertain"})
                self.assertEqual(machine.data["brand"], "CAT")
                self.machine.refresh_from_db()
