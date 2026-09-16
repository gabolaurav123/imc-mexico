"""Photos remain useful without a plate; owner declarations stay authoritative."""
from copy import deepcopy
from io import BytesIO
from tempfile import TemporaryDirectory
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from portal.models import AnalysisJob, Category, Consent, Machine, Publication, User
from portal.processing import ingest_asset
from portal.research import (ResearchExtraction, ResearchField, empty_research,
                             merge_research, normalize_research)
from portal.services import (apply_analysis_automatically, automatic_application_snapshot,
                             save_draft, submit_machine)


VISIBLE = "Equipo sobre orugas con brazo articulado y cucharón visibles en las fotografías."


@override_settings(PRIVATE_S3_BUCKET="")
class VisualCompletionTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory(prefix="imc-visual-completion-")
        self.addCleanup(folder.cleanup)
        override = override_settings(MEDIA_ROOT=folder.name)
        override.enable()
        self.addCleanup(override.disable)
        self.owner = User.objects.create_user(email="visual-completion@example.invalid", is_test=True)
        self.machine = Machine.objects.create(owner=self.owner)
        self.category = Category.objects.create(name="Excavadoras", slug="excavadoras")
        raw = BytesIO()
        Image.new("RGB", (90, 60), "yellow").save(raw, format="JPEG")
        self.asset = ingest_asset(self.machine, self.owner, SimpleUploadedFile("general.jpg", raw.getvalue()), purpose="general")
        Consent.objects.create(user=self.owner, machine=self.machine, kind="ai", granted=True)

    def result(self, visual=VISIBLE):
        return {"title": "Excavadora", "category": "Excavadoras", "visual_description": visual,
                "data": {"description": "Texto recompuesto anterior que no debe copiarse: potencia 999 kW."},
                "provenance": {"description": {"source": "system", "review": "needs_review"}},
                "fields": [], "plates": [], "warnings": [],
                "research": empty_research("insufficient_identifiers")}

    def job(self, result):
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, asset_ids=[str(self.asset.pk)], fingerprint=uuid.uuid4().hex,
            status="completed", auto_apply=True, application_snapshot=automatic_application_snapshot(self.machine),
            result=result)

    def apply(self, job):
        self.machine, summary = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        return summary

    def add_ocr_serial(self, result, value="OCR-OTHER999"):
        result["data"]["serial"] = value
        result["provenance"]["serial"] = {"source": "plate", "review": "clear", "component": "machine",
                                           "asset_id": str(self.asset.pk), "evidence": value}
        result["plates"] = [{"asset_id": str(self.asset.pk), "component": "machine",
                              "readability": "clear", "transcription": value}]
        return result

    def test_general_photos_without_identifiers_preserve_visual_description_and_stay_private(self):
        summary = self.apply(self.job(self.result()))
        self.assertIn("description", summary["applied_fields"])
        self.assertIn(VISIBLE, self.machine.data["description"])
        self.assertNotIn("999", self.machine.data["description"])
        self.assertEqual(self.machine.category, self.category)
        self.assertEqual(self.machine.provenance["description"]["review"], "needs_review")
        for field in ("serial", "brand", "model", "year", "power", "location"):
            self.assertNotIn(field, self.machine.data)
        self.assertEqual(self.machine.status, "draft")
        self.assertFalse(Publication.objects.exists())
        submission = submit_machine(self.machine, self.owner, True)
        self.assertIn(VISIBLE, submission.version.data["data"]["description"])
        self.assertFalse(Publication.objects.exists())

    def test_category_context_does_not_apply_generic_specs_as_unit_values(self):
        result = self.result()
        result["research"] = {**empty_research("general_context"), "basis": "category", "match": "category",
            "identity": {"serial": None, "brand": None, "model": None, "category": "Excavadoras"},
            "context": {"category": "Excavadoras", "label": "Referencias generales; no identifican esta unidad"},
            "sources": [{"url": "https://www.cat.com/equipment/excavators", "title": "Excavadoras"}]}
        result["data"]["power"] = "500 kW"
        result["provenance"]["power"] = {"source": "web", "review": "needs_review", "component": "machine",
                                             "scope": "category"}
        summary = self.apply(self.job(result))
        self.assertNotIn("power", summary["applied_fields"])
        self.assertNotIn("power", self.machine.data)
        self.assertIn(VISIBLE, self.machine.data["description"])
        self.assertNotIn("500", self.machine.data["description"])

    def test_manually_declared_serial_without_plate_photo_wins_over_ocr(self):
        self.machine = save_draft(self.machine, self.owner, {"data": {"serial": "OWNER-123"}}, self.machine.revision)
        self.assertFalse(self.machine.assets.filter(purpose="plate").exists())
        summary = self.apply(self.job(self.add_ocr_serial(self.result())))
        self.assertEqual(self.machine.data["serial"], "OWNER-123")
        self.assertEqual(self.machine.provenance["serial"], {"source": "user", "review": "confirmed"})
        self.assertNotIn("serial", summary["applied_fields"])
        self.assertNotIn("OWNER-123", self.machine.data["description"])
        self.assertNotIn("OCR-OTHER999", self.machine.data["description"])
        self.assertIn(VISIBLE, self.machine.data["description"])

    def test_serial_changed_while_running_blocks_old_unit_reference_without_losing_user_value(self):
        self.machine = save_draft(self.machine, self.owner,
            {"data": {"brand": "Caterpillar", "model": "420F2", "serial": "OLD123"}}, self.machine.revision)
        url = "https://www.cat.com/equipment/420f2"
        evidence = "Caterpillar 420F2 serie OLD123: potencia 70 kW."
        research = normalize_research(ResearchExtraction(fields=[ResearchField(key="power", value="70 kW",
            scope="exact_serial", source_url=url, evidence=evidence, matched_serial="OLD123",
            matched_brand="Caterpillar", matched_model="420F2")]),
            {"serial": "OLD123", "brand": "Caterpillar", "model": "420F2"}, "exact_serial",
            [{"url": url, "title": "Cat"}], evidence, citations={url: [evidence]})
        result = merge_research(self.result(), research)
        job = self.job(self.add_ocr_serial(result, "OLD123"))
        self.machine = save_draft(self.machine, self.owner, {"data": {"serial": "CORRECTED456"}}, self.machine.revision)
        summary = self.apply(job)
        self.assertEqual(self.machine.data["serial"], "CORRECTED456")
        self.assertNotIn("power", self.machine.data)
        self.assertEqual(summary["field_reasons"]["power"], "identity_changed")
        for private in ("OLD123", "CORRECTED456", "70 kW"):
            self.assertNotIn(private, self.machine.data["description"])

    def test_deliberately_blank_serial_is_preserved_even_for_a_legacy_completed_job(self):
        self.machine = save_draft(self.machine, self.owner, {"data": {"serial": ""}}, self.machine.revision)
        job = self.job(self.add_ocr_serial(self.result()))
        job.application_snapshot = {}
        job.save(update_fields=["application_snapshot"])
        summary = self.apply(job)
        self.assertEqual(self.machine.data["serial"], "")
        self.assertEqual(summary["field_reasons"]["serial"], "human_correction")

    def test_human_description_and_human_clear_are_preserved_with_new_visual_narrative(self):
        for value in ("Descripción escrita por el propietario.", ""):
            with self.subTest(value=value):
                job = self.job(self.result())
                self.machine = save_draft(self.machine, self.owner, {"data": {"description": value}}, self.machine.revision)
                summary = self.apply(job)
                self.assertEqual(self.machine.data["description"], value)
                self.assertNotIn("description", summary["applied_fields"])

    def test_uncertain_technical_value_cannot_return_through_visual_text(self):
        result = self.result("Equipo de orugas con potencia de 80 kW y cucharón visible.")
        result["data"]["power"] = "80 kW"
        result["provenance"]["power"] = {"source": "image", "review": "needs_review", "component": "machine",
                                             "asset_id": str(self.asset.pk)}
        self.apply(self.job(result))
        self.assertNotIn("power", self.machine.data)
        self.assertNotIn("80 kW", self.machine.data["description"])

    def test_old_combined_description_is_not_used_as_a_visual_fallback(self):
        result = self.result()
        result.pop("visual_description")
        self.apply(self.job(result))
        self.assertNotIn("999", self.machine.data["description"])
        self.assertNotIn("Texto recompuesto", self.machine.data["description"])

    def test_changed_human_category_cannot_be_reintroduced_by_old_visual_narrative(self):
        job = self.job(self.result())
        corrected = Category.objects.create(name="Grúas", slug="gruas")
        self.machine = save_draft(self.machine, self.owner, {"category": corrected.pk}, self.machine.revision)
        self.apply(job)
        self.assertEqual(self.machine.category, corrected)
        self.assertNotIn(VISIBLE, self.machine.data["description"])
        self.assertIn("Grúas", self.machine.data["description"])
