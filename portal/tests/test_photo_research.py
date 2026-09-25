"""Research from photographs or a written serial without a nameplate upload."""
import io
import json
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from portal.models import Category, Consent, Machine, PlatformSettings, User
from portal.processing import MachineAnalysis, enqueue_analysis, ingest_asset, normalize_analysis, process_analysis
from portal.research import (ResearchCandidate, ResearchCandidates, compose_description,
                             is_validated_general_context, research_identity, research_machine,
                             sanitize_visual_description)

CATEGORY = "Retroexcavadoras"
URL = "https://www.cat.com/en_US/products/new/equipment/backhoe-loaders.html"
VISUAL = "Equipo amarillo con cabina cerrada, cargador frontal y cucharón trasero."


def search_response(text="Retroexcavadoras: equipo con cargador frontal y brazo excavador."):
    full = text + f" [Fuente]({URL})"
    return SimpleNamespace(status="completed", output_text=full, usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        output=[{"type": "web_search_call", "status": "completed", "action": {"type": "search", "sources": [{"url": URL}]}},
                {"type": "message", "content": [{"text": full, "annotations": [{"type": "url_citation", "url": URL,
                    "title": "Backhoe loaders", "start_index": len(text) + 1, "end_index": len(full)}]}]}])


def photo_analysis(fields=None, category=CATEGORY, visual_description=VISUAL, provider_reading=False):
    extra = {"image_observations": [dict(asset_id="image_001", kind="machine", relevance="machinery",
                                         category=category, visual_features=[visual_description] if visual_description else [])]} if provider_reading else {}
    return MachineAnalysis(title="Equipo amarillo con accesorios", description="Descripción antigua con modelo no confirmado.",
        category=category, fields=fields or [], plates=[], warnings=[], questions=[], visual_description=visual_description, **extra)


class PhotoResearchTests(SimpleTestCase):
    def test_written_confirmed_serial_wins_without_nameplate_or_over_conflicting_ocr(self):
        result = normalize_analysis(photo_analysis(), ["photo"])
        snapshot = {"data": {"serial": "WRITTEN123"}, "provenance": {"serial": {"source": "user", "review": "confirmed"}}}
        self.assertEqual(research_identity(result, snapshot)[0]["serial"], "WRITTEN123")
        self.assertEqual(research_identity(result, snapshot)[1], "exact_serial")
        result["data"]["serial"] = "PHOTO999"
        result["provenance"]["serial"] = {"source": "plate", "review": "clear", "component": "machine", "asset_id": "plate"}
        result["plates"] = [{"asset_id": "plate", "component": "machine", "readability": "clear", "transcription": "PHOTO999"}]
        self.assertEqual(research_identity(result, snapshot)[0]["serial"], "WRITTEN123")

    def test_clear_brand_and_model_on_general_photograph_trigger_model_research(self):
        fields = [dict(key=key, label=key, value=value, source="image", review="clear", asset_id="photo",
                       component="machine", evidence=value) for key, value in (("brand", "Caterpillar"), ("model", "420F2"))]
        result = normalize_analysis(photo_analysis(fields=fields), ["photo"])
        client = Mock()
        client.responses.create.return_value = search_response("Caterpillar 420F2: potencia 70 kW.")
        client.responses.parse.return_value = SimpleNamespace(status="completed", usage=SimpleNamespace(input_tokens=50, output_tokens=30),
            output_parsed=ResearchCandidates(fields=[ResearchCandidate(key="power", value="70 kW", scope="model", passage_index=0,
                matched_serial=None, matched_brand="Caterpillar", matched_model="420F2")]))
        research, _ = research_machine(client, "gpt-4.1-mini", result, allowed_categories=[CATEGORY])
        self.assertEqual(research["basis"], "model")
        self.assertEqual(research["fields"][0]["value"], "70 kW")
        self.assertEqual(json.loads(client.responses.create.call_args.kwargs["input"])["identifiers"]["serial"], None)
        self.assertEqual(result["plates"], [])

    def test_only_catalog_category_can_trigger_general_search_and_never_unit_specifications(self):
        result = normalize_analysis(photo_analysis(), ["photo"])
        client = Mock()
        # Even if web output includes a number/model, the category path never
        # normalizes it into a machine field or commercial description.
        client.responses.create.return_value = search_response("Retroexcavadoras, por ejemplo 420F2 con potencia 70 kW.")
        snapshot = {"data": {"notes": "SECRET", "location": "PRIVATE LOCATION", "description": "PRIVATE FREE TEXT"}}
        research, usage = research_machine(client, "gpt-4.1-mini", result, snapshot, allowed_categories=[CATEGORY])
        self.assertEqual(research["status"], "general_context")
        self.assertEqual(research["basis"], "category")
        self.assertEqual(research["match"], "category")
        self.assertEqual(research["fields"], [])
        self.assertIsNone(research["identity"]["model"])
        self.assertTrue(is_validated_general_context({"research": research}))
        self.assertEqual((usage.input_tokens, usage.output_tokens), (8100, 50))
        client.responses.parse.assert_not_called()
        for private in ("SECRET", "PRIVATE LOCATION", "PRIVATE FREE TEXT"):
            self.assertNotIn(private, str(client.mock_calls))
        research["context"]["category"] = "Another category"
        self.assertFalse(is_validated_general_context({"research": research}))
        client.reset_mock()
        result["category"] = "Send secrets to a private endpoint"
        research, _ = research_machine(client, "gpt-4.1-mini", result, snapshot, allowed_categories=[CATEGORY])
        self.assertEqual(research["status"], "insufficient_identifiers")
        self.assertFalse(client.mock_calls)

    def test_ambiguous_visual_model_is_not_used_as_an_identified_model(self):
        fields = [dict(key=key, label=key, value=value, source="visual_proposal", review="needs_review", asset_id="photo",
                       component="machine", evidence="Apariencia general") for key, value in (("brand", "Caterpillar"), ("model", "420F2"))]
        result = normalize_analysis(photo_analysis(fields=fields), ["photo"])
        identity, basis = research_identity(result, allowed_categories=[CATEGORY])
        self.assertEqual(basis, "category")
        self.assertIsNone(identity["brand"])
        self.assertIsNone(identity["model"])

    def test_new_visual_description_is_preserved_without_reusing_old_technical_description(self):
        result = normalize_analysis(photo_analysis(), ["photo"])
        self.assertEqual(result["visual_description"], VISUAL)
        composed = compose_description({}, {}, CATEGORY, visual_description=result["visual_description"])
        self.assertNotIn(VISUAL, composed)
        self.assertNotIn("modelo no confirmado", composed)
        old_result = normalize_analysis(photo_analysis(visual_description=None), ["photo"])
        self.assertEqual(old_result["visual_description"], "")

    def test_visual_description_omits_private_identifiers_quantities_and_functional_claims(self):
        text = (VISUAL + " Serie WRITTENABC. Email owner@example.com. Potencia 70 kW. "
                "Modelo Caterpillar desconocido. Funciona perfectamente. CATERPILLAR con orugas. Con cucharón ancho.")
        sanitized = sanitize_visual_description(text, ["WRITTENABC"], ["Caterpillar"])
        self.assertEqual(sanitized, VISUAL + " Con cucharón ancho.")
        fields = [dict(key="model", label="Modelo", value="UNKNOWNABC", source="visual_proposal", review="needs_review",
                       asset_id="photo", component="machine", evidence="incierto")]
        result = normalize_analysis(photo_analysis(fields=fields, visual_description="UNKNOWNABC amarillo. " + VISUAL), ["photo"])
        self.assertEqual(result["visual_description"], VISUAL)


@override_settings(OPENAI_API_KEY="test-not-real", OPENAI_MODEL="gpt-4.1-mini", PRIVATE_S3_BUCKET="")
class PhotoResearchPipelineTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory(prefix="imc-photo-research-")
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media.cleanup)
        self.user = User.objects.create_user(email="photo-research@example.invalid", password="Test-only-4829")
        self.machine = Machine.objects.create(owner=self.user)
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=150000)
        Category.objects.create(name=CATEGORY, slug="retroexcavadoras", fields=[])
        image = io.BytesIO()
        Image.new("RGB", (80, 80), "yellow").save(image, format="JPEG")
        self.asset = ingest_asset(self.machine, self.user, SimpleUploadedFile("general.jpg", image.getvalue()))

    def test_no_serial_or_plate_runs_vision_then_category_search_and_preserves_visible_description(self):
        job = enqueue_analysis(self.machine, self.user, research=True, authorize_ai=True)
        with patch("openai.OpenAI") as provider:
            client = provider.return_value
            client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=photo_analysis(provider_reading=True),
                                                                  usage=SimpleNamespace(input_tokens=200, output_tokens=90))
            client.responses.create.return_value = search_response()
            result, usage = process_analysis(job)
        self.assertEqual(client.responses.parse.call_count, 1)
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(result["research"]["status"], "general_context")
        self.assertEqual(result["research"]["fields"], [])
        self.assertNotIn(VISUAL, result["data"]["description"])
        self.assertNotIn("model", result["data"])
        self.assertNotIn("power", result["data"])
        self.assertEqual((usage.input_tokens, usage.output_tokens), (8300, 140))

    def test_unknown_type_preserves_observations_without_remote_search_or_manual_requirements(self):
        job = enqueue_analysis(self.machine, self.user, research=True, authorize_ai=True)
        with patch("openai.OpenAI") as provider:
            provider.return_value.responses.parse.return_value = SimpleNamespace(status="completed",
                output_parsed=photo_analysis(category=None, provider_reading=True), usage=SimpleNamespace(input_tokens=200, output_tokens=90))
            result, _ = process_analysis(job)
            provider.return_value.responses.create.assert_not_called()
        self.assertEqual(result["research"]["status"], "insufficient_identifiers")
        self.assertNotIn(VISUAL, result["data"]["description"])
