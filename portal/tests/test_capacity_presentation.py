"""A platform's literal load is never presented as a bucket volume."""
from io import BytesIO
import json
from uuid import uuid4
import zipfile

from django.test import Client, TestCase, override_settings
from pypdf import PdfReader

from portal.export_payload import build_export_payload
from portal.models import AnalysisJob, Category, Machine, PreparedShare, User
from portal.pdf import build_pdf
from portal.processing import normalize_analysis
from portal.services import snapshot
from portal.sheet_details import build_technical_summary
from portal.tests.test_plate_enrichment import plate_analysis
from portal.views import sheet_context


@override_settings(STAFF_MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False, PUBLIC_URL="https://example.invalid", STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class CapacityPresentationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="platform-capacity@example.invalid", is_test=True)
        self.category = Category.objects.create(name="Plataformas elevadoras", slug="plataformas-elevadoras")
        self.values = {"brand": "Genie", "model": "GS-1930", "serial": "GS3016A-151046", "year": 2016,
                       "weight": "2742 lbs / 1244 kg", "capacity": "500 lbs / 227 kg"}
        self.machine = Machine.objects.create(owner=self.owner, category=self.category,
            title="Plataforma Genie GS-1930", data=self.values)
        self.client.force_login(self.owner)

    def test_plate_reading_retains_capacity_and_weight_as_separate_literal_fields(self):
        parsed = plate_analysis(category=self.category.name,
            fields=[dict(key=key, label=key, value=str(value), source="plate", review="clear",
                         asset_id="plate-image", component="machine", evidence=f"{key}: {value}")
                    for key, value in self.values.items()],
            plates=[dict(asset_id="plate-image", component="machine", readability="clear",
                         transcription="\n".join(f"{key}: {value}" for key, value in self.values.items()))])
        result = normalize_analysis(parsed, ["plate-image"])
        self.assertEqual(result["data"]["capacity"], "500 lbs / 227 kg")
        self.assertEqual(result["data"]["weight"], "2742 lbs / 1244 kg")
        self.assertNotIn("bucket_capacity", result["data"])

    def test_preview_and_shared_sheet_label_platform_load_and_keep_literal_value(self):
        AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, revision=self.machine.revision,
            status="completed", mode="description", fingerprint=uuid4().hex, result={})
        preview = self.client.get(f"/panel/maquinarias/{self.machine.pk}/ficha/")
        self.assertContains(preview, "Capacidad de plataforma")
        self.assertContains(preview, self.values["capacity"])
        self.assertNotContains(preview, "cucharón")
        shared = self.client.post(f"/api/maquinarias/{self.machine.pk}/compartir/",
            json.dumps({"revision": self.machine.revision}), content_type="application/json")
        self.assertEqual(shared.status_code, 200, shared.content)
        share = PreparedShare.objects.get(machine=self.machine)
        public = Client().get(f"/s/{share.code}/")
        self.assertContains(public, "Capacidad de plataforma")
        self.assertContains(public, self.values["capacity"])
        self.assertNotContains(public, "cucharón")
        self.assertEqual(share.snapshot["data"]["capacity"], self.values["capacity"])

    def test_snapshot_category_controls_html_pdf_and_export_after_draft_category_changes(self):
        version = snapshot(self.machine, self.owner)
        self.machine.approved_version = version
        self.machine.category = Category.objects.create(name="Excavadoras", slug="excavadoras")
        self.machine.save(update_fields=["approved_version", "category"])
        for public in (False, True):
            with self.subTest(public=public):
                context = sheet_context(self.machine, version, public=public)
                field = next(item for item in context["essential_fields"] if item["key"] == "capacity")
                self.assertEqual(field["label"], "Capacidad de plataforma")
                self.assertEqual(field["value"], self.values["capacity"])
                pdf = PdfReader(BytesIO(build_pdf(self.machine, self.machine.data, [], public=public, version=version)))
                text = " ".join(" ".join(page.extract_text() for page in pdf.pages).split())
                self.assertIn("CAPACIDAD DE PLATAFORMA", text)
                self.assertIn(self.values["capacity"], text)
                self.assertNotIn("cucharón", text.casefold())
        payload, _ = build_export_payload(self.machine, version)
        self.assertEqual(payload["category"], self.category.name)
        self.assertEqual(payload["data"]["capacity"], self.values["capacity"])
        self.assertIsNone(payload["data"].get("capacity_m3"))
        self.assertEqual(version.data["data"]["capacity"], self.values["capacity"])

    def test_imc_export_text_and_json_keep_the_platform_capacity(self):
        from portal.integration import prepare_delivery, record_manual_review
        self.owner.advertiser_status = "approved"
        self.owner.save(update_fields=["advertiser_status"])
        publisher = User.objects.create_superuser(email="capacity-export@example.invalid", password=None)
        version = snapshot(self.machine, self.owner)
        self.machine.approved_version = version
        self.machine.save(update_fields=["approved_version"])
        payload, _ = build_export_payload(self.machine, version)
        delivery = prepare_delivery(self.machine, publisher, payload)
        record_manual_review(delivery, publisher, imc_advertiser="Cuenta de prueba",
                             duplicate_result="no_match", evidence="Revisión de duplicados del paquete de prueba.")
        self.client.force_login(publisher)
        response = self.client.post(f"/operaciones/maquinarias/{self.machine.pk}/exportar/")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(BytesIO(response.content)) as package:
            text = package.read(f"ficha_{self.machine.folio}_{version.number}/datos_para_imc.txt").decode()
            exported = json.loads(package.read("publicacion.json"))
        self.assertIn("Capacidad de plataforma: 500 lbs / 227 kg", text)
        self.assertNotIn("cucharón", text)
        self.assertEqual(exported["data"]["capacity"], self.values["capacity"])

    def test_other_families_use_their_existing_capacity_meaning_and_unknown_stays_generic(self):
        for name, expected in (("Montacargas", "Capacidad nominal"), ("Minicargadores", "Capacidad operativa nominal"),
                               ("Excavadoras", "Capacidad del cucharón"), ("Equipo sin perfil", "Capacidad")):
            with self.subTest(category=name):
                self.machine.category = Category.objects.create(name=name, slug=name.lower().replace(" ", "-"))
                context = sheet_context(self.machine)
                field = next(item for item in context["essential_fields"] if item["key"] == "capacity")
                self.assertEqual(field["label"], expected)
        summary = " ".join(build_technical_summary({"capacity": self.values["capacity"]}, category=self.category.name))
        self.assertIn("Capacidad de plataforma: 500 lbs / 227 kg", summary)
