"""Independent observations survive when another visual sentence is unsafe."""
from io import BytesIO
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from portal.models import Category, Machine, PlatformSettings, Publication, User
from portal.processing import (MachineAnalysis, enqueue_analysis, ingest_asset,
                               normalize_analysis, process_next_job)
from portal.services import save_draft


FEATURES = ["Cabina cerrada visible", "Pintura amarilla", "Hoja niveladora central visible"]


def parsed_result(asset="photo", **overrides):
    fields = [dict(key=key, label=key, value=value, source="image", review="clear", asset_id=asset,
                   component="machine", evidence=value) for key, value in (("brand", "CAT"), ("model", "14H"))]
    data = dict(title="Motoniveladora CAT 14H", description="Texto anterior con datos que no se deben reciclar.",
        category="Motoniveladoras", fields=fields, plates=[], warnings=[], questions=[],
        visual_description="CAT 14H de color amarillo, con 6 ruedas, cabina cerrada y hoja niveladora central.",
        visual_features=FEATURES)
    data.update(overrides)
    return MachineAnalysis(**data)


class VisualFeatureNormalizationTests(SimpleTestCase):
    def test_safe_features_survive_a_rejected_combined_description(self):
        result = normalize_analysis(parsed_result(), ["photo"])
        for feature in FEATURES:
            self.assertIn(feature, result["visual_description"])
        for rejected in ("CAT", "14H", "6 ruedas", "Texto anterior"):
            self.assertNotIn(rejected, result["visual_description"])
        self.assertEqual(result["visual_features"], [feature + "." for feature in FEATURES])
        self.assertEqual(result["data"]["brand"], "CAT")
        self.assertEqual(result["data"]["model"], "14H")
        self.assertEqual(result["provenance"]["brand"]["source"], "image")

    def test_each_private_technical_or_functional_feature_is_omitted_independently(self):
        features = ["Cabina cerrada", "Serie OWNERABC", "Correo owner@example.com", "Potencia 70 kW",
                    "Funciona perfectamente", "CAT amarillo", "14H con ruedas", "https://www.cat.com/",
                    "Sin fallas", "Ruedas visibles"]
        result = normalize_analysis(parsed_result(visual_description=None, visual_features=features), ["photo"])
        self.assertEqual(result["visual_features"], ["Cabina cerrada.", "Ruedas visibles."])
        self.assertEqual(result["visual_description"], "Cabina cerrada. Ruedas visibles.")

    def test_valid_prose_and_features_combine_without_duplicate_observations(self):
        result = normalize_analysis(parsed_result(visual_description="Cabina cerrada.", visual_features=[
            "cabina cerrada", "Pintura amarilla", "Pintura amarilla.", "", " "]), ["photo"])
        self.assertEqual(result["visual_description"], "Cabina cerrada. Pintura amarilla.")
        self.assertEqual(result["visual_features"], ["cabina cerrada.", "Pintura amarilla."])

    def test_legacy_analysis_without_visual_fields_does_not_reuse_raw_description(self):
        data = parsed_result().model_dump(exclude={"visual_description", "visual_features"})
        result = normalize_analysis(MachineAnalysis(**data), ["photo"])
        self.assertEqual(result["visual_description"], "")
        self.assertEqual(result["visual_features"], [])


@override_settings(OPENAI_API_KEY="test-only-not-real", OPENAI_MODEL="gpt-4.1-mini", PRIVATE_S3_BUCKET="")
class VisualFeatureWorkerTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory(prefix="imc-visual-feature-test-")
        self.addCleanup(folder.cleanup)
        override = override_settings(MEDIA_ROOT=folder.name)
        override.enable()
        self.addCleanup(override.disable)
        self.owner = User.objects.create_user(email="visual-features@example.invalid", is_test=True)
        self.machine = Machine.objects.create(owner=self.owner)
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=150000)
        Category.objects.create(name="Motoniveladoras", slug="motoniveladoras")
        raw = BytesIO()
        Image.new("RGB", (90, 60), "yellow").save(raw, format="JPEG")
        self.asset = ingest_asset(self.machine, self.owner, SimpleUploadedFile("general.jpg", raw.getvalue()))

    def queue(self):
        return enqueue_analysis(self.machine, self.owner, auto_apply=True, research=True, authorize_ai=True,
                                expected_revision=self.machine.revision)

    def provider_response(self):
        return SimpleNamespace(status="completed", output_parsed=parsed_result("image_001",
            image_observations=[dict(asset_id="image_001", kind="machine", relevance="machinery",
                                     category="Motoniveladoras", visual_features=FEATURES)]),
                               usage=SimpleNamespace(input_tokens=100, output_tokens=90))

    def test_worker_saves_visible_features_without_serial_or_successful_web_research(self):
        job = self.queue()
        with patch("openai.OpenAI") as provider:
            provider.return_value.responses.parse.return_value = self.provider_response()
            provider.return_value.responses.create.side_effect = TimeoutError("search failed")
            self.assertTrue(process_next_job())
        self.machine.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.result["research"]["status"], "degraded")
        for feature in FEATURES:
            self.assertIn(feature, self.machine.data["description"])
        self.assertNotIn("Texto anterior", self.machine.data["description"])
        self.assertNotIn("6 ruedas", self.machine.data["description"])
        self.assertEqual(self.machine.provenance["description"]["review"], "needs_review")
        self.assertEqual(self.machine.provenance["description"]["analysis_id"], str(job.pk))
        self.assertNotIn("serial", self.machine.data)
        self.assertFalse(Publication.objects.exists())

    def test_new_visual_features_do_not_overwrite_a_concurrent_human_description(self):
        self.queue()
        self.machine = save_draft(self.machine, self.owner,
            {"data": {"description": "Descripción corregida por el propietario."}}, self.machine.revision)
        with patch("openai.OpenAI") as provider:
            provider.return_value.responses.parse.return_value = self.provider_response()
            provider.return_value.responses.create.side_effect = TimeoutError("search failed")
            process_next_job()
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.data["description"], "Descripción corregida por el propietario.")
        self.assertEqual(self.machine.provenance["description"]["source"], "user")
        self.assertEqual(self.machine.provenance["description"]["review"], "confirmed")
        self.assertTrue(self.machine.provenance["description"]["source_date"])
