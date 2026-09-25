import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from portal.models import (AnalysisJob, Asset, Category, Consent, Machine, MachineVersion,
                           PlatformSettings, Publication, Submission, User)
from portal.processing import enqueue_analysis, ingest_asset, normalize_analysis, process_analysis, process_next_job
from portal.services import apply_analysis_automatically, save_draft
from portal.tests.test_processing import analysis_result, photo


@override_settings(OPENAI_API_KEY="test-only-not-a-key", PRIVATE_S3_BUCKET="", SECURE_SSL_REDIRECT=False)
class AutomaticCompletionTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="imc-autocomplete-test-")
        self.addCleanup(self.folder.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.folder.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.owner = User.objects.create_user(email="autofill@example.invalid", is_test=True)
        self.machine = Machine.objects.create(owner=self.owner)
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=600000)
        self.asset = ingest_asset(self.machine, self.owner, photo())
        self.category = Category.objects.create(name="Excavadoras", slug="excavadoras")
        Consent.objects.create(user=self.owner, machine=self.machine, kind="ai", granted=True)

    def result(self):
        source = {"source": "image", "review": "clear", "asset_id": str(self.asset.pk),
                  "component": "machine", "evidence": "Texto visible de prueba"}
        fields = [{**source, "key": "brand", "label": "Marca", "value": "MARCA DE PRUEBA"},
                  {**source, "key": "model", "label": "Modelo", "value": "MODELO DE PRUEBA"},
                  {**source, "key": "hours", "label": "Horas", "value": "1000", "review": "needs_review"},
                  {**source, "key": "year", "label": "Año", "value": None, "review": "not_identifiable"},
                  {**source, "key": "serial", "label": "Serie motor", "value": "ENGINE-123", "source": "plate", "component": "engine"}]
        parsed = analysis_result(str(self.asset.pk), fields=fields, plates=[{
            "asset_id": str(self.asset.pk), "component": "engine", "transcription": "ENGINE-123", "readability": "clear"}])
        return normalize_analysis(parsed, [str(self.asset.pk)])

    def enqueue(self, **kwargs):
        return enqueue_analysis(self.machine, self.owner, auto_apply=True,
                                expected_revision=self.machine.revision, **kwargs)

    def run_worker(self, job, during=None):
        result = self.result()

        def remote(_job):
            if during:
                during()
            return result, SimpleNamespace(input_tokens=100, output_tokens=30)

        with patch("portal.processing.process_analysis", side_effect=remote):
            self.assertTrue(process_next_job())
        self.machine.refresh_from_db()
        job.refresh_from_db()
        return job

    def test_worker_completes_private_draft_without_browser_and_preserves_ai_review(self):
        before = self.machine.revision
        job = self.run_worker(self.enqueue())
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.application_result["status"], "applied")
        self.assertEqual(self.machine.title, "Excavadora")
        self.assertEqual(self.machine.category, self.category)
        self.assertEqual(self.machine.data["brand"], "MARCA DE PRUEBA")
        self.assertNotIn("hours", self.machine.data)
        self.assertNotIn("year", self.machine.data)
        self.assertNotIn("serial", self.machine.data)
        self.assertEqual(self.machine.provenance["brand"]["review"], "clear")
        self.assertEqual(self.machine.provenance["title"]["review"], "needs_review")
        self.assertEqual(self.machine.provenance["brand"]["analysis_id"], str(job.pk))
        self.assertEqual(self.machine.revision, before + 1)
        self.assertEqual(self.machine.status, "draft")
        self.assertFalse(MachineVersion.objects.exists())
        self.assertFalse(Submission.objects.exists())
        self.assertFalse(Publication.objects.exists())

    def test_concurrent_human_values_and_explicit_clear_are_preserved_but_other_gaps_fill(self):
        job = self.enqueue()

        def human_edit():
            self.machine = save_draft(self.machine, self.owner,
                                     {"data": {"brand": "MI MARCA CORREGIDA", "model": "", "location": "Ubicación declarada"}},
                                     self.machine.revision)

        self.run_worker(job, human_edit)
        self.assertEqual(self.machine.data["brand"], "MI MARCA CORREGIDA")
        self.assertEqual(self.machine.data["model"], "")
        self.assertEqual(self.machine.data["location"], "Ubicación declarada")
        self.assertTrue(self.machine.data["description"])
        self.assertEqual(job.application_result["field_reasons"]["model"], "human_correction")
        self.assertEqual(job.application_result["revision_after"], job.application_result["revision_before"] + 1)

    def test_idempotent_retry_cannot_reinsert_later_cleared_human_correction(self):
        job = self.run_worker(self.enqueue())
        original_result = job.application_result.copy()
        self.machine = save_draft(self.machine, self.owner, {"data": {"brand": ""}}, self.machine.revision)
        revision = self.machine.revision
        machine, result = apply_analysis_automatically(self.machine, self.owner, job, original_result["revision_before"])
        self.assertEqual(machine.data["brand"], "")
        self.assertEqual(machine.revision, revision)
        self.assertEqual(result, original_result)
        self.assertFalse(process_next_job())

    def test_media_changes_during_analysis_prevent_application(self):
        job = self.enqueue()
        self.run_worker(job, lambda: ingest_asset(self.machine, self.owner, photo(color="green")))
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.application_result["reason"], "assets_changed")
        self.assertEqual(self.machine.title, "Mi maquinaria")
        self.assertEqual(self.machine.data, {})

    def test_document_added_during_analysis_does_not_invalidate_photo_result(self):
        job = self.enqueue()

        def add_manual():
            Asset.objects.create(machine=self.machine, kind="image", purpose="document", processing_status="ready",
                original="test/manual.jpg", mime_type="image/jpeg", sha256="d" * 64, size=1)

        self.run_worker(job, add_manual)
        self.assertEqual(job.application_result["status"], "applied")
        self.assertNotEqual(job.application_result["reason"], "assets_changed")
        self.assertEqual(self.machine.data["brand"], "MARCA DE PRUEBA")

    def test_legacy_snapshot_with_document_keeps_photo_application_valid(self):
        manual = Asset.objects.create(machine=self.machine, kind="image", purpose="document", processing_status="ready",
            original="test/manual.jpg", mime_type="image/jpeg", sha256="d" * 64, size=1)
        job = self.enqueue()
        job.application_snapshot["assets"] = [{"id": str(asset.pk), "sha256": asset.sha256,
            "purpose": asset.purpose, "kind": asset.kind, "status": asset.processing_status}
            for asset in self.machine.assets.order_by("id")]
        self.assertIn(str(manual.pk), [asset["id"] for asset in job.application_snapshot["assets"]])
        job.save(update_fields=["application_snapshot"])

        self.run_worker(job)
        self.assertEqual(job.application_result["status"], "applied")
        self.assertNotEqual(job.application_result["reason"], "assets_changed")
        self.assertEqual(self.machine.data["brand"], "MARCA DE PRUEBA")

    def test_revoked_consent_after_remote_call_preserves_result_without_application(self):
        job = self.enqueue()
        self.run_worker(job, lambda: Consent.objects.create(user=self.owner, machine=self.machine, kind="ai", granted=False))
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.application_result["reason"], "consent_revoked")
        self.assertTrue(job.result["data"]["brand"])
        self.assertEqual(self.machine.data, {})

    def test_submitted_or_reassigned_machine_is_not_modified(self):
        for change, reason in [(lambda: Machine.objects.filter(pk=self.machine.pk).update(status="submitted"), "not_editable"),
                               (lambda: Machine.objects.filter(pk=self.machine.pk).update(owner=User.objects.create_user(email="new-owner@example.invalid")), "owner_changed")]:
            with self.subTest(reason=reason):
                self.machine.status = "draft"
                self.machine.owner = self.owner
                self.machine.revision += 1
                self.machine.save()
                job = self.enqueue()
                self.run_worker(job, change)
                self.assertEqual(job.application_result["reason"], reason)
                self.assertEqual(self.machine.data, {})

    def test_new_job_respects_preexisting_human_empty_field(self):
        self.machine = save_draft(self.machine, self.owner, {"data": {"brand": ""}}, self.machine.revision)
        job = self.run_worker(self.enqueue())
        self.assertEqual(self.machine.data["brand"], "")
        self.assertNotIn("brand", job.application_result["applied_fields"])

    def test_legacy_completed_job_fills_blank_old_form_once_without_spending_tokens(self):
        self.machine.data = {"brand": "", "location": "Se conserva"}
        self.machine.provenance = {"brand": {"source": "user", "review": "confirmed"}}
        self.machine.save()
        job = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, revision=self.machine.revision,
            asset_ids=[str(self.asset.pk)], fingerprint=uuid.uuid4().hex, status="completed", result=self.result(), input_tokens=123)
        with patch("portal.processing.process_analysis") as remote:
            machine, result = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        remote.assert_not_called()
        self.assertEqual(machine.data["brand"], "MARCA DE PRUEBA")
        self.assertEqual(machine.data["location"], "Se conserva")
        self.assertEqual(machine.provenance["brand"]["review"], "clear")
        self.assertEqual(result["status"], "applied")
        job.refresh_from_db()
        self.assertEqual(job.input_tokens, 123)
        self.assertEqual(AnalysisJob.objects.count(), 1)

    def test_legacy_job_with_later_changes_cannot_fill_even_empty_field(self):
        job = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, revision=self.machine.revision,
            asset_ids=[str(self.asset.pk)], fingerprint=uuid.uuid4().hex, status="completed", result=self.result())
        self.machine = save_draft(self.machine, self.owner, {"data": {"brand": ""}}, self.machine.revision)
        machine, result = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        self.assertEqual(result["reason"], "draft_changed")
        self.assertEqual(machine.data, {"brand": ""})

    def test_opt_in_can_upgrade_duplicate_queued_job_without_another_api_request(self):
        original = enqueue_analysis(self.machine, self.owner)
        duplicate = self.enqueue()
        self.assertEqual(duplicate.pk, original.pk)
        self.assertTrue(duplicate.auto_apply)
        self.assertEqual(AnalysisJob.objects.count(), 1)
        self.run_worker(duplicate)
        self.assertEqual(self.machine.data["brand"], "MARCA DE PRUEBA")

    def test_autofill_failure_does_not_lose_completed_ai_result(self):
        job = self.enqueue()
        def fail_after_partial_write(*args, **kwargs):
            Machine.objects.filter(pk=self.machine.pk).update(title="PARTIAL WRITE MUST ROLLBACK")
            raise ValidationError("private details")

        with patch("portal.processing.apply_analysis_automatically", side_effect=fail_after_partial_write):
            self.run_worker(job)
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.application_result["reason"], "application_failed")
        self.assertNotIn("private details", str(job.application_result))
        self.assertTrue(job.result["data"]["brand"])
        self.assertEqual(self.machine.title, "Mi maquinaria")
        with patch("portal.processing.process_analysis") as remote:
            machine, result = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        remote.assert_not_called()
        self.assertEqual(result["status"], "applied")
        self.assertEqual(machine.data["brand"], "MARCA DE PRUEBA")
        job.refresh_from_db()
        self.assertEqual(job.input_tokens, 100)
        self.assertEqual(AnalysisJob.objects.count(), 1)

    def test_explicit_new_button_consent_renews_latest_revocation(self):
        self.machine.category = self.category
        self.machine.save(update_fields=["category"])
        Consent.objects.create(user=self.owner, machine=self.machine, kind="ai", granted=False)
        self.client.force_login(self.owner)
        response = self.client.post(f"/api/maquinarias/{self.machine.pk}/analizar/",
                                    {"consent": True, "auto_apply": True, "revision": self.machine.revision},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Consent.objects.filter(user=self.owner, machine=self.machine, kind="ai").order_by("-created_at", "-pk").first().granted)
        self.assertTrue(response.json()["auto_apply"]["requested"])

    def test_prompt_receives_active_category_names_only_without_private_snapshot(self):
        Category.objects.create(name="Categoría no disponible", slug="inactive", active=False)
        self.machine.data = {"contact_public": "PRIVATE CONTACT", "notes": "PRIVATE NOTES"}
        self.machine.save()
        job = self.enqueue()
        with patch("openai.OpenAI") as client:
            client.return_value.responses.parse.return_value = SimpleNamespace(status="completed",
                output_parsed=analysis_result("image_001", image_observations=[dict(asset_id="image_001", kind="machine", relevance="machinery")]), usage=SimpleNamespace(input_tokens=1, output_tokens=1))
            process_analysis(job)
        import json
        prompt = json.loads(client.return_value.responses.parse.call_args.kwargs["input"][0]["content"][0]["text"])
        self.assertEqual(prompt["allowed_category_names"], ["Excavadoras"])
        self.assertNotIn("PRIVATE", str(prompt))
        self.assertNotIn("owner_id", str(prompt))
        self.assertNotIn("eligible_fields", str(prompt))

    def test_inactive_category_and_invalid_numeric_field_are_not_applied(self):
        self.category.active = False
        self.category.save()
        job = self.enqueue()
        result = self.result()
        result["data"]["year"] = "20500"
        result["provenance"]["year"]["review"] = "clear"
        with patch("portal.processing.process_analysis", return_value=(result, SimpleNamespace(input_tokens=1, output_tokens=1))):
            process_next_job()
        self.machine.refresh_from_db()
        job.refresh_from_db()
        self.assertIsNone(self.machine.category_id)
        self.assertNotIn("year", self.machine.data)
        self.assertEqual(self.machine.data["brand"], "MARCA DE PRUEBA")
        self.assertEqual(job.application_result["field_reasons"]["year"], "invalid_value")
        self.assertEqual(Category.objects.count(), 1)
