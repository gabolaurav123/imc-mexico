"""A nameplate describes equipment; old AI readings are not owner declarations."""
from io import BytesIO
import json
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from portal.models import Category, Machine, PlatformSettings, User
from portal.processing import MachineAnalysis, enqueue_analysis, ingest_asset, normalize_analysis, process_analysis
from portal.research import (ResearchExtraction, ResearchField,
                             explicit_manufacturing_origin, merge_research, normalize_research,
                             research_identity, research_machine)
from portal.tests.test_research import web_response


VALUES = {"brand": "ACME", "model": "CP-90", "serial": "000739120044", "weight": "90 kg",
          "power": "4.8 kW / 6.5 HP", "vibration_frequency": "4200 VPM",
          "centrifugal_force": "13 kN", "compaction_depth": "30 cm"}


def plate_analysis(asset="plate-image", **overrides):
    data = dict(title="Placa de compactadora ACME", description="Placa metálica negra con cuatro tornillos.",
        category="Compactadores", fields=[dict(key=key, label=key, value=value, source="plate",
            review="clear", asset_id=asset, component="machine", evidence=f"{key}: {value}")
            for key, value in VALUES.items()], plates=[dict(asset_id=asset, component="machine", readability="clear",
            transcription="\n".join(f"{key}: {value}" for key, value in VALUES.items()))], warnings=[], questions=[],
        visual_description="Placa metálica negra con letras blancas.", visual_features=["Cuatro tornillos visibles"],
        image_observations=[dict(asset_id=asset, kind="plate")])
    data.update(overrides)
    return MachineAnalysis(**data)


class PlateEquipmentTests(SimpleTestCase):
    def test_plate_only_preserves_machine_facts_and_discards_label_appearance(self):
        result = normalize_analysis(plate_analysis(), ["plate-image"])
        self.assertEqual(result["data"]["title"], "Compactador ACME CP-90")
        for key, value in VALUES.items():
            self.assertEqual(result["data"][key], value)
            self.assertEqual(result["provenance"][key]["source"], "plate")
            self.assertEqual(result["provenance"][key]["review"], "clear")
        self.assertEqual(result["visual_description"], "")
        self.assertEqual(result["visual_features"], [])
        self.assertIn("frecuencia de vibración", result["data"]["description"])
        for value in ("4200 VPM", "13 kN", "30 cm", "4.8 kW"):
            self.assertIn(value, result["data"]["description"])
        for value in (VALUES["serial"], "metal", "tornillos", "letras"):
            self.assertNotIn(value, result["data"]["description"])
        self.assertEqual(research_identity(result)[1], "exact_serial")

    def test_numeric_leading_zero_serial_is_kept_but_ambiguous_reading_is_not_reconstructed(self):
        data = plate_analysis().model_dump()
        serial = next(field for field in data["fields"] if field["key"] == "serial")
        serial.update(value=None, review="needs_review", evidence="Primer dígito borroso")
        result = normalize_analysis(MachineAnalysis(**data), ["plate-image"])
        # A seemingly complete transcription alone cannot fill a doubtful field.
        self.assertIsNone(result["data"]["serial"])
        self.assertEqual(research_identity(result)[1], "model")
        serial.update(value=VALUES["serial"], review="clear")
        data["plates"][0].update(readability="partial", transcription="Nº de serie: [ilegible]00739120044")
        self.assertIsNone(normalize_analysis(MachineAnalysis(**data), ["plate-image"])["data"]["serial"])

    def test_component_plate_never_becomes_machine_model_serial_or_new_specs(self):
        data = plate_analysis().model_dump()
        for field in data["fields"]:
            field["component"] = "engine"
        data["plates"][0]["component"] = "engine"
        result = normalize_analysis(MachineAnalysis(**data), ["plate-image"])
        self.assertFalse(set(VALUES) & result["data"].keys())
        self.assertEqual(research_identity(result)[1], "none")

    def test_plate_compactor_is_a_machine_type_and_mixed_photos_keep_equipment_observations(self):
        result = normalize_analysis(plate_analysis(title="Placa compactadora ACME CP-90"), ["plate-image"])
        self.assertEqual(result["title"], "Placa compactadora ACME CP-90")
        result = normalize_analysis(plate_analysis(visual_description="Manillar visible.", visual_features=["Base metálica visible"],
            image_observations=[dict(asset_id="plate-image", kind="plate"), dict(asset_id="general-image", kind="machine")]),
            ["plate-image", "general-image"])
        self.assertIn("Manillar visible", result["visual_description"])
        self.assertIn("Base metálica visible", result["visual_description"])
        with self.assertRaises(ValidationError):
            normalize_analysis(plate_analysis(image_observations=[dict(asset_id="foreign", kind="plate")]), ["plate-image"])

    def test_country_requires_explicit_manufacture_and_never_slogan_address_or_serial_decoding(self):
        for evidence in ("ACME ist Qualität. Alemania", "Sede del fabricante: Alemania", "Serie iniciada por DE: Alemania",
                         "Fabricado en China; sede en Alemania", "País de origen de la marca: Alemania"):
            with self.subTest(evidence=evidence):
                self.assertFalse(explicit_manufacturing_origin(evidence, "Alemania"))
        data = plate_analysis().model_dump()
        field = dict(key="country_of_origin", label="País de fabricación", value="Alemania", source="plate",
            review="clear", asset_id="plate-image", component="machine", evidence="Sede: Alemania")
        data["fields"].append(field)
        self.assertIsNone(normalize_analysis(MachineAnalysis(**data), ["plate-image"])["data"]["country_of_origin"])
        field.update(value="China", evidence="Made in China")
        data["plates"][0]["transcription"] += "\nMade in China"
        self.assertEqual(normalize_analysis(MachineAnalysis(**data), ["plate-image"])["data"]["country_of_origin"], "China")

    def test_previous_ai_identifiers_do_not_anchor_new_reading_but_human_values_and_clears_do(self):
        result = normalize_analysis(plate_analysis(), ["plate-image"])
        previous = {"data": {"brand": "OLD", "model": "OLD90", "serial": "OLD123"},
            "provenance": {key: {"source": "plate", "review": "clear", "analysis_id": "old-job"} for key in ("brand", "model", "serial")}}
        self.assertEqual(research_identity(result, previous)[0], {key: VALUES[key] for key in ("serial", "brand", "model")})
        previous["provenance"] = {key: {"source": "user", "review": "confirmed"} for key in previous["data"]}
        self.assertEqual(research_identity(result, previous)[0], previous["data"])
        previous["data"].update(serial="", model="")
        identity, basis = research_identity(result, previous)
        self.assertIsNone(identity["serial"])
        self.assertIsNone(identity["model"])
        self.assertEqual(basis, "none")

    def test_verified_web_specs_and_explicit_origin_retain_citations_without_current_location(self):
        identity = {"brand": "ACME", "model": "CP-90", "serial": None}
        url = "https://www.acme.example.com/cp-90"
        text = "ACME CP-90: frecuencia 4200 VPM, fuerza 13 kN, profundidad 30 cm. Made in China."
        fields = [ResearchField(key=key, value=value, scope="model", source_url=url, evidence=text,
            matched_brand="ACME", matched_model="CP-90", matched_serial=None) for key, value in {
                "vibration_frequency": "4200 VPM", "centrifugal_force": "13 kN", "compaction_depth": "30 cm",
                "country_of_origin": "China", "location": "China"}.items()]
        outcome = normalize_research(ResearchExtraction(fields=fields), identity, "model", [{"url": url, "title": "ACME CP-90"}],
                                    text, citations={url: [text]})
        self.assertEqual({field["key"] for field in outcome["fields"]}, {
            "vibration_frequency", "centrifugal_force", "compaction_depth", "country_of_origin"})
        result = merge_research({"data": {}, "provenance": {}, "fields": [], "warnings": []}, outcome)
        self.assertNotIn("location", result["data"])
        for key in result["data"]:
            self.assertEqual(result["provenance"][key]["review"], "needs_review")
            self.assertEqual(result["provenance"][key]["source_url"], url)
        bad_text = "ACME CP-90: sede del fabricante en Alemania."
        fields[3] = fields[3].model_copy(update={"value": "Alemania", "evidence": bad_text})
        rejected = normalize_research(ResearchExtraction(fields=[fields[3]]), identity, "model", [{"url": url, "title": "ACME CP-90"}],
                                     bad_text, citations={url: [bad_text]})
        self.assertEqual(rejected["fields"], [])

    def test_category_with_known_brand_does_not_report_other_manufacturers_as_research(self):
        result = normalize_analysis(plate_analysis(fields=[plate_analysis().fields[0]]), ["plate-image"])
        client = Mock()
        client.responses.create.return_value = web_response()
        outcome, _ = research_machine(client, "gpt-4.1-mini", result, allowed_categories=["Compactadores"])
        self.assertEqual(outcome["basis"], "category")
        self.assertEqual(outcome["status"], "no_results")
        self.assertEqual(outcome["fields"], [])
        self.assertEqual(outcome["sources"], [])
        client.responses.parse.assert_not_called()

    def test_unsuccessful_model_research_does_not_display_similar_brand_or_geographic_names(self):
        identity = {"brand": "HESSEN", "model": "016-9020", "serial": None}
        url = "https://www.example.com/unrelated"
        for title, passage in (("HESSNE 016-9020", "HESSNE 016-9020, otro fabricante."),
                               ("Hessen", "Hessen es una región de Alemania.")):
            with self.subTest(title=title):
                outcome = normalize_research(ResearchExtraction(fields=[]), identity, "model", [{"url": url, "title": title}],
                    passage, citations={url: [passage]}, source_titles={url: title})
                self.assertEqual(outcome["sources"], [])
                self.assertEqual(outcome["status"], "no_results")


@override_settings(OPENAI_API_KEY="test-only-not-real", OPENAI_MODEL="gpt-4.1-mini", PRIVATE_S3_BUCKET="")
class PlateReanalysisPipelineTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory(prefix="imc-plate-reanalysis-")
        self.addCleanup(folder.cleanup)
        override = override_settings(MEDIA_ROOT=folder.name)
        override.enable()
        self.addCleanup(override.disable)
        self.owner = User.objects.create_user(email="plate-reanalysis@example.invalid", is_test=True)
        Category.objects.create(name="Compactadores", slug="compactadores")
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=100000)
        self.machine = Machine.objects.create(owner=self.owner, title="Título previo de IA", data={"power": "4.5 kW", "brand": "OLD"},
            provenance={key: {"source": "plate", "review": "clear", "analysis_id": "old-job"} for key in ("power", "brand")})
        image = BytesIO()
        Image.new("RGB", (90, 60), "navy").save(image, format="JPEG")
        self.asset = ingest_asset(self.machine, self.owner, SimpleUploadedFile("label.jpg", image.getvalue()))

    def test_new_reading_and_description_ignore_previous_ai_values_without_paid_calls(self):
        job = enqueue_analysis(self.machine, self.owner, research=True, authorize_ai=True,
                               expected_revision=self.machine.revision)
        self.assertEqual(job.result["input_snapshot"]["provenance"]["power"]["analysis_id"], "old-job")
        response = SimpleNamespace(status="completed", output_parsed=plate_analysis(str(self.asset.pk)),
                                   usage=SimpleNamespace(input_tokens=150, output_tokens=100))
        with patch("openai.OpenAI") as provider:
            provider.return_value.responses.parse.return_value = response
            provider.return_value.responses.create.side_effect = TimeoutError("synthetic unavailable search")
            result, _ = process_analysis(job)
        request = json.loads(provider.return_value.responses.parse.call_args.kwargs["input"][0]["content"][0]["text"])
        self.assertEqual(request["declared_data"]["data"], {})
        self.assertIsNone(request["recorded_data"])
        self.assertEqual(result["data"]["power"], VALUES["power"])
        self.assertIn("4.8 kW", result["data"]["description"])
        self.assertNotIn("4.5 kW", result["data"]["description"])
        self.assertEqual(result["research"]["identity"]["brand"], "ACME")
        self.assertEqual(result["research"]["status"], "degraded")
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.data["power"], "4.5 kW")  # Extraction alone does not mutate drafts.
