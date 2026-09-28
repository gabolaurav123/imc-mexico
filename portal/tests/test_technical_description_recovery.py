"""A readable plate can complete prose without spending another analysis."""
from copy import deepcopy
from io import BytesIO
import json
from types import SimpleNamespace
import uuid

from django.test import Client, SimpleTestCase, TestCase, override_settings
from pypdf import PdfReader

from portal.description_quality import has_technical_description
from portal.intake import preparation_completeness
from portal.models import AnalysisJob, Asset, Category, Machine, PreparedShare, User
from portal.pdf import build_pdf
from portal.public_data import public_projection
from portal.services import save_draft
from portal.sheet_details import build_technical_summary, clean_sheet_text
from portal.technical_description import description_projection, recovered_technical_description
from portal.views import machine_state


DATA = {
    "brand": "Genie", "model": "GS-1930", "serial": "PRIVATE-GS-151046", "year": 2016,
    "weight": "2742 lbs / 1244 kg", "capacity": "500 lbs / 227 kg", "gradeability": "25 % / 14°",
    "estimate_min": 4000, "estimate_max": 18000, "estimate_currency": "USD",
    "description": "Plataformas elevadoras Genie GS-1930.\nDatos principales: Peso: 2742 lbs / 1244 kg · Capacidad: 500 lbs / 227 kg.",
    "plate_transcription": "PRIVATE PLATE TRANSCRIPTION", "contact_public": "private@example.invalid",
}
META = {key: {"source": "plate", "review": "clear", "component": "machine"}
        for key in ("brand", "model", "serial", "year", "weight", "capacity", "gradeability")}
META["description"] = {"source": "system", "review": "needs_review"}
CATEGORY = "Plataformas elevadoras"


class TechnicalDescriptionRecoveryTests(SimpleTestCase):
    def test_three_independent_plate_facts_form_useful_lines_without_identity_padding(self):
        original = deepcopy((DATA, META))
        result = recovered_technical_description(DATA, META, category=CATEGORY)
        self.assertEqual(result.splitlines(), [
            "Peso según la placa: 2742 lbs / 1244 kg.",
            "Capacidad de plataforma según la placa: 500 lbs / 227 kg.",
            "Pendiente superable según la placa: 25 % / 14°.",
        ])
        self.assertTrue(has_technical_description(result))
        self.assertEqual(clean_sheet_text(result), result)
        self.assertEqual((DATA, META), original)
        self.assertEqual(recovered_technical_description({**DATA, "gradeability": None}, META), "")
        self.assertNotIn("Genie", result)
        self.assertNotIn("operativo", result)

    def test_human_copy_and_insufficient_or_unsafe_evidence_remain_unmodified(self):
        for value, meta in (("", {"source": "user"}), ("Texto propio.", {"source": "user"}),
                            (DATA["description"], {"source": "system", "review": "confirmed"}),
                            ("Texto sin procedencia.", {})):
            with self.subTest(value=value, meta=meta):
                data, provenance = {**DATA, "description": value}, {**META, "description": meta}
                self.assertEqual(description_projection(data, provenance)["description"], value)
        for changes in ({"review": "needs_review"}, {"review_reason": "conflicting_reading"},
                        {"source": "web"}, {"source": "unknown"}, {"component": "engine"}, {"component": None}):
            with self.subTest(changes=changes):
                provenance = {**META, "gradeability": {**META["gradeability"], **changes}}
                self.assertEqual(recovered_technical_description(DATA, provenance), "")
        for unsafe in ("25 % PRIVATE-GS-151046", "25 % por confirmar", "25 % pendiente", "25 % https://private.invalid",
                       "25 % <script>", "25 %\nPRIVATE", "25 % " + "x" * 150, True):
            with self.subTest(unsafe=unsafe):
                self.assertEqual(recovered_technical_description({**DATA, "gradeability": unsafe}, META), "")
        meta = deepcopy(META)
        meta["gradeability"]["matched_serial"] = "OTHER-PRIVATE-123"
        self.assertEqual(recovered_technical_description({**DATA, "gradeability": "25 % OTHER-PRIVATE-123"}, meta), "")

    def test_paired_units_and_conditions_are_not_split_into_extra_summary_lines(self):
        data = {**DATA, "weight": "2742 lbs; 1244 kg", "capacity": "500 lbs; 227 kg"}
        projected = description_projection(data, META, category=CATEGORY)
        for provenance in (META, {}):
            with self.subTest(provenance=bool(provenance)):
                lines = build_technical_summary(projected, provenance, category=CATEGORY)
                self.assertEqual(lines, projected["description"].splitlines())
                self.assertEqual(len(lines), 3)
                self.assertIn("25 % / 14°", lines[-1])
        data["capacity"] = "2250 kg a 600 mm; 1950 kg a 760 mm"
        self.assertIn(data["capacity"], recovered_technical_description(data, META, category="Montacargas"))

    def test_technical_slope_is_distinct_from_unresolved_workflow_copy(self):
        accepted = "Pendiente superable según la placa: 25 % / 14°."
        self.assertEqual(clean_sheet_text(accepted), accepted)
        for text in ("Pendiente de confirmar.", "Datos pendientes.", "Pendiente superable por confirmar: 25 %."):
            with self.subTest(text=text):
                self.assertEqual(clean_sheet_text(text), "")
                self.assertFalse(has_technical_description("\n".join([
                    "Peso según la placa: 2742 lbs / 1244 kg.",
                    "Capacidad de plataforma según la placa: 500 lbs / 227 kg.", text])))


@override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_URL="https://example.invalid")
class ExistingPlateShareRecoveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="plate-recovery@example.invalid", phone="+525512345678")
        category = Category.objects.create(name=CATEGORY, slug="plataformas-elevadoras")
        self.machine = Machine.objects.create(owner=self.user, category=category, title="Genie GS-1930",
                                              data=deepcopy(DATA), provenance=deepcopy(META))
        self.plate = Asset.objects.create(machine=self.machine, kind="image", purpose="plate", processing_status="ready",
                                         sha256="a" * 64, mime_type="image/jpeg", size=1, original="private/plate.jpg")
        self.job = AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, status="completed", mode="analysis",
            revision=self.machine.revision, fingerprint=uuid.uuid4().hex, asset_ids=[str(self.plate.pk)],
            input_tokens=123, output_tokens=45, result={"completion": {"missing_fields": ["description"]},
                "relevance": {"status": "relevant", "accepted_asset_ids": [str(self.plate.pk)]}})
        for meta in self.machine.provenance.values():
            meta["analysis_id"] = str(self.job.pk)
            if meta.get("source") == "plate":
                meta["asset_id"] = str(self.plate.pk)
        self.machine.save()
        self.client.force_login(self.user)
        self.url = f"/api/maquinarias/{self.machine.pk}/compartir/"

    def share(self):
        return self.client.post(self.url, json.dumps({"revision": self.machine.revision}), content_type="application/json")

    def test_existing_genie_editor_preview_share_and_pdf_agree_without_job_or_draft_writes(self):
        before = deepcopy((self.machine.data, self.machine.provenance, self.machine.revision))
        expected = recovered_technical_description(self.machine.data, self.machine.provenance, category=CATEGORY)
        self.assertEqual(preparation_completeness(self.machine, self.job)["missing_fields"], [])
        self.assertEqual(machine_state(self.machine)["data"]["description"], expected)
        editor = self.client.get(f"/panel/maquinarias/{self.machine.pk}/")
        self.assertEqual(editor.context["data"]["description"], expected)
        preview = self.client.get(f"/panel/maquinarias/{self.machine.pk}/ficha/")
        self.assertEqual(preview.context["technical_summary_lines"], expected.splitlines())
        response = self.share()
        self.assertEqual(response.status_code, 200, response.content)
        share = PreparedShare.objects.get(machine=self.machine)
        self.assertEqual(share.snapshot["data"]["description"], expected)
        self.assertEqual(share.snapshot["public_asset_ids"], [])
        public = Client().get(response.json()["url"].removeprefix("https://example.invalid"))
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.context["technical_summary_lines"], expected.splitlines())
        for secret in (DATA["serial"], DATA["plate_transcription"], DATA["contact_public"], str(self.plate.pk)):
            self.assertNotContains(public, secret)
        pdf = PdfReader(BytesIO(build_pdf(self.machine, {}, [], public=True,
            version=SimpleNamespace(data=share.snapshot, created_at=share.created_at, number=share.revision))))
        pdf_text = " ".join(" ".join(page.extract_text() for page in pdf.pages).split())
        for line in expected.splitlines():
            self.assertIn(line, pdf_text)
        self.machine.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual((self.machine.data, self.machine.provenance, self.machine.revision), before)
        self.assertEqual(AnalysisJob.objects.count(), 1)
        self.assertEqual((self.job.input_tokens, self.job.output_tokens), (123, 45))

    def test_current_human_correction_removal_and_conflict_change_recovery_without_stale_text(self):
        shared = self.share()
        self.assertEqual(shared.status_code, 200)
        snapshot = deepcopy(PreparedShare.objects.get().snapshot)
        self.machine = save_draft(self.machine, self.user, {"data": {"weight": "1300 kg"}}, self.machine.revision)
        description = machine_state(self.machine)["data"]["description"]
        self.assertIn("1300 kg", description)
        self.assertNotIn("1244 kg", description)
        self.assertIn("1244 kg", public_projection(snapshot)["description"])
        self.machine = save_draft(self.machine, self.user, {"data": {"gradeability": None}}, self.machine.revision)
        self.assertIn("description", preparation_completeness(self.machine)["missing_fields"])
        self.assertEqual(self.share().status_code, 400)
        self.assertNotIn("25 %", machine_state(self.machine)["data"]["description"])
        self.machine.data["gradeability"] = DATA["gradeability"]
        self.machine.provenance["gradeability"] = {**META["gradeability"], "review_reason": "conflicting_reading"}
        self.machine.save()
        self.assertEqual(self.share().status_code, 400)
        self.machine = save_draft(self.machine, self.user, {"data": {"description": "Descripción escrita por el propietario."}}, self.machine.revision)
        self.assertEqual(self.share().status_code, 200)
        self.assertEqual(PreparedShare.objects.get().snapshot["data"]["description"], self.machine.data["description"])

    def test_category_specific_line_limit_is_the_same_for_readiness_and_sharing(self):
        self.machine.data["capacity"] = "500 lbs / 227 kg " + "condición " * 10
        self.machine.save()
        # The generic heading fits, but the platform-specific heading must not
        # let readiness promise a recovery that the public sheet cannot use.
        self.assertTrue(recovered_technical_description(self.machine.data, self.machine.provenance))
        self.assertFalse(recovered_technical_description(self.machine.data, self.machine.provenance, category=CATEGORY))
        self.assertIn("description", preparation_completeness(self.machine)["missing_fields"])
        self.assertEqual(self.share().status_code, 400)
