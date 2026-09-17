"""Literal plate fields survive save, autofill and private/public documents."""
from copy import deepcopy
from io import BytesIO
from uuid import uuid4

from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from pypdf import PdfReader

from portal.models import AnalysisJob, Asset, Category, Consent, Machine, User
from portal.pdf import build_pdf
from portal.services import (PLATE_TECHNICAL_LABELS, apply_analysis_automatically,
    automatic_application_snapshot, save_draft, snapshot)
from portal.views import sheet_context


# Synthetic examples retain literal qualifiers and units; no catalogue lookup.
PLATE_VALUES = {
    "front_tire_size": "21x7x15", "rear_tire_size": "16x6x10.5",
    "mast_tilt": "Rearward 6 deg", "load_tire_tread": "34.5 in",
    "manufacturer": "Fabricante de prueba Inc.", "manufacturer_address": "Houston, USA",
    "voltage": "48 V", "lift_height": "188 in", "load_center": "24 in",
    "battery_weight": "MIN 1800 lb / MAX 2200 lb", "battery_capacity": "600 Ah", "fork_length": "42 in",
}


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class ForkliftSheetFieldsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="forklift-fields@example.invalid", is_test=True)
        self.category = Category.objects.create(name="Montacargas", slug="montacargas", fields=[])
        self.machine = Machine.objects.create(owner=self.owner, title="Montacargas sintético", category=self.category)
        self.asset = Asset.objects.create(machine=self.machine, kind="image", purpose="plate",
            processing_status="ready", sha256="a" * 64, original="test/forklift.jpg", size=1, mime_type="image/jpeg")
        Consent.objects.create(user=self.owner, machine=self.machine, kind="ai", granted=True)

    def job(self, values=None):
        values = deepcopy(PLATE_VALUES if values is None else values)
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, fingerprint=uuid4().hex, status="completed", auto_apply=True,
            application_snapshot=automatic_application_snapshot(self.machine), asset_ids=[str(self.asset.pk)],
            result={"data": values, "provenance": {key: {"source": "plate", "review": "clear",
                "component": "machine", "asset_id": str(self.asset.pk), "evidence": f"{key}: {value}"}
                for key, value in values.items()}, "fields": [], "plates": []})

    def apply(self, job):
        self.machine, result = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        return result

    def test_all_literal_fields_apply_without_a_category_schema_or_inferred_location(self):
        self.machine.category = None
        self.machine.save(update_fields=["category"])
        result = self.apply(self.job())
        self.assertEqual(set(result["applied_fields"]), set(PLATE_VALUES))
        self.assertEqual(self.machine.data, PLATE_VALUES)
        self.assertNotIn("location", self.machine.data)
        self.assertNotIn("country_of_origin", self.machine.data)
        self.assertNotIn("capacity", self.machine.data)
        self.assertTrue(all(meta["source"] == "plate" for meta in self.machine.provenance.values()))

    def test_clear_serial_line_applies_even_when_another_plate_line_is_partial(self):
        job = self.job({"serial": "TEST-FORK1234", **PLATE_VALUES})
        job.result["plates"] = [{"asset_id": str(self.asset.pk), "component": "machine", "readability": "partial",
            "transcription": "Serial: TEST-FORK1234\nCapacity: [ilegible]\nFront tires: 21x7x15"}]
        job.save(update_fields=["result"])
        result = self.apply(job)
        self.assertIn("serial", result["applied_fields"])
        self.assertEqual(self.machine.data["serial"], "TEST-FORK1234")
        self.assertNotIn("capacity", self.machine.data)

    def test_partial_serial_line_does_not_apply_despite_other_clear_plate_fields(self):
        job = self.job({"serial": "TEST-FORK1234", **PLATE_VALUES})
        job.result["plates"] = [{"asset_id": str(self.asset.pk), "component": "machine", "readability": "partial",
            "transcription": "Serial: TEST-FORK1234?\nFront tires: 21x7x15"}]
        job.save(update_fields=["result"])
        result = self.apply(job)
        self.assertNotIn("serial", result["applied_fields"])
        self.assertNotIn("serial", self.machine.data)
        self.assertEqual(self.machine.data["front_tire_size"], "21x7x15")

    def test_manual_fields_save_and_same_image_numeric_conflicts_preserve_human_corrections(self):
        self.apply(self.job())
        self.machine = save_draft(self.machine, self.owner,
            {"data": {"front_tire_size": "Corrección humana 21x7x15", "battery_capacity": None}}, self.machine.revision)
        changed = {**PLATE_VALUES, "front_tire_size": "20x7x15", "rear_tire_size": "16x6x10.6", "battery_capacity": "750 Ah"}
        result = self.apply(self.job(changed))
        self.assertEqual(self.machine.data["front_tire_size"], "Corrección humana 21x7x15")
        self.assertIsNone(self.machine.data["battery_capacity"])
        self.assertEqual(self.machine.data["rear_tire_size"], PLATE_VALUES["rear_tire_size"])
        self.assertEqual(result["field_reasons"]["rear_tire_size"], "conflicting_reading")

    def test_virtual_sheet_and_public_snapshot_render_all_fields_without_compactor_links(self):
        self.machine = save_draft(self.machine, self.owner, {"data": {**PLATE_VALUES, "weight": "4500 kg"}}, self.machine.revision)
        version = snapshot(self.machine, self.owner)
        for public in (False, True):
            with self.subTest(public=public):
                context = sheet_context(self.machine, version, public=public, token="synthetic")
                context["user"] = self.owner
                values = {field["key"]: field["value"] for field in context["extra_fields"]}
                self.assertEqual({key: values[key] for key in PLATE_VALUES}, PLATE_VALUES)
                html = render_to_string("portal/sheet.html", context)
                for key, value in PLATE_VALUES.items():
                    self.assertIn(value, html)
                    self.assertIn(PLATE_TECHNICAL_LABELS[key], html)
                self.assertNotIn("husqvarna", html.lower())
                self.assertNotIn("wacker", html.lower())
                self.assertEqual(context["data"].get("location"), None)
                self.assertEqual(context["data"].get("country_of_origin"), None)

    def test_pdf_prints_all_literal_values_and_labels_without_altering_ranges(self):
        self.machine = save_draft(self.machine, self.owner, {"data": PLATE_VALUES}, self.machine.revision)
        version = snapshot(self.machine, self.owner)
        for public in (False, True):
            with self.subTest(public=public):
                document = PdfReader(BytesIO(build_pdf(self.machine, self.machine.data, [], public=public, version=version)))
                text = " ".join(" ".join(page.extract_text() for page in document.pages).split())
                for key, value in PLATE_VALUES.items():
                    self.assertIn(value, text)
                    self.assertIn(PLATE_TECHNICAL_LABELS[key], text)

    def test_new_fields_cannot_reintroduce_private_serial_in_public_html_or_pdf(self):
        data = {**PLATE_VALUES, "serial": "PRIVATE-FORK1234", "manufacturer_address": "Houston PRIVATE-FORK1234"}
        self.machine = save_draft(self.machine, self.owner, {"data": data}, self.machine.revision)
        version = snapshot(self.machine, self.owner)
        context = sheet_context(self.machine, version, public=True, token="synthetic")
        self.assertNotIn("serial", context["data"])
        self.assertNotIn("manufacturer_address", context["data"])
        document = PdfReader(BytesIO(build_pdf(self.machine, context["data"], [], public=True, version=version)))
        self.assertNotIn("PRIVATE-FORK1234", " ".join(page.extract_text() for page in document.pages))
        self.assertEqual(version.data["data"], data)

    def test_historical_category_controls_reference_not_live_category(self):
        self.machine.data = {"weight": "4500 kg"}
        self.machine.save(update_fields=["data"])
        version = snapshot(self.machine, self.owner)
        self.machine.category = Category.objects.create(name="Compactadores", slug="compactadores")
        self.machine.save(update_fields=["category"])
        current = sheet_context(self.machine)["technical_interpretation"]
        historical = sheet_context(self.machine, version)["technical_interpretation"]
        self.assertTrue(current[0]["reference"].get("url"))
        self.assertEqual(historical[0]["reference"], {})
