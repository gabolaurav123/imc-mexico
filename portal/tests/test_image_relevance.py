"""Per-image relevance, legacy compatibility and no paid search for unrelated uploads."""
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from portal.models import Asset, Category, Machine, PlatformSettings, User
from portal.processing import (MachineAnalysis, normalize_analysis, enqueue_analysis,
                               process_analysis, process_next_job)
from portal.research import UsageTotals, empty_research


def field(key, value, asset_id, source="image"):
    return dict(key=key, label=key, value=value, source=source, review="clear",
                component="machine", asset_id=asset_id, evidence=f"{key}: {value}")


def observation(asset_id, relevance="machinery", kind="machine", **kwargs):
    return dict(asset_id=asset_id, relevance=relevance, kind=kind, **kwargs)


def parsed(observations, fields=(), plates=()):
    return MachineAnalysis(title="TÍTULO GLOBAL AJENO", description="Persona con camisa azul.",
        category="Categoría global ajena", fields=list(fields), plates=list(plates),
        warnings=["AVISO DEL CONTENIDO AJENO"], questions=["Pregunta ajena"],
        visual_description="Mascota de color blanco.", visual_features=["Persona con sombrero."],
        image_observations=observations)


class ImageRelevanceNormalizationTests(SimpleTestCase):
    def test_strict_provider_schema_requires_classification_and_per_image_fields(self):
        from openai.lib._pydantic import to_strict_json_schema
        schema = to_strict_json_schema(MachineAnalysis)["$defs"]["ImageObservation"]
        self.assertTrue({"asset_id", "kind", "relevance", "category", "visual_features"} <= set(schema["required"]))
        self.assertFalse(schema["additionalProperties"])

    def test_legacy_observation_without_explicit_classification_remains_unassessed(self):
        for observations in (None, [{"asset_id": "old", "kind": "machine"}]):
            with self.subTest(observations=observations):
                response = parsed(observations or [], [field("brand", "Legacy", "old")])
                if observations is None:
                    legacy = response.model_dump(exclude_unset=True)
                    legacy.pop("image_observations")
                    response = MachineAnalysis(**legacy)
                result = normalize_analysis(response, ["old"])
                self.assertEqual(result["relevance"]["status"], "unassessed")
                self.assertEqual(result["data"]["brand"], "Legacy")
                self.assertEqual(result["title"], "TÍTULO GLOBAL AJENO")

    def test_explicit_empty_observations_for_received_images_is_uncertain(self):
        result = normalize_analysis(parsed([], [field("brand", "Invented", "a")]), ["a"])
        self.assertEqual(result["relevance"]["status"], "uncertain")
        self.assertEqual(result["relevance"]["uncertain_asset_ids"], ["a"])
        self.assertEqual(result["data"], {})
        self.assertEqual(result["title"], "")

    def test_all_unrelated_or_uncertain_clear_every_proposal_and_raw_plate(self):
        for status in ("unrelated", "uncertain"):
            with self.subTest(status=status):
                response = parsed([observation("a", status, "other", category="Montacargas",
                    visual_features=["Mascota blanca."])], [field("brand", "Personal", "a")],
                    [{"asset_id": "a", "component": "machine", "readability": "clear", "transcription": "PRIVATE TEXT"}])
                result = normalize_analysis(response, ["a"], allowed_categories=["Montacargas"])
                self.assertEqual(result["relevance"]["status"], status)
                for key in ("data", "provenance"):
                    self.assertEqual(result[key], {})
                for key in ("title", "description", "visual_description"):
                    self.assertEqual(result[key], "")
                for key in ("fields", "plates", "visual_features", "questions"):
                    self.assertEqual(result[key], [])
                self.assertIsNone(result["category"])
                self.assertNotIn("PRIVATE TEXT", str(result))
                self.assertNotIn("Mascota", str(result))
                self.assertEqual(result["warnings"], [result["relevance"]["message"]])

    def test_missing_or_conflicting_observations_cannot_claim_all_unrelated(self):
        cases = [([observation("a", "unrelated", "other")], ["a", "b"]),
                 ([observation("a", "unrelated", "other"), observation("a", "machinery")], ["a"]),
                 ([observation("a", "unrelated", "other"), observation("a", "unrelated", "machine")], ["a"]),
                 ([observation("a", "unrelated", "other"), {"asset_id": "b", "kind": "machine"}], ["a", "b"])]
        for observations, ids in cases:
            with self.subTest(observations=observations):
                result = normalize_analysis(parsed(observations), ids)
                self.assertEqual(result["relevance"]["status"], "uncertain")
                self.assertTrue(result["relevance"]["uncertain_asset_ids"])
                self.assertEqual(result["data"], {})

    def test_mixed_filters_before_duplicates_and_keeps_only_bound_machine_features(self):
        observations = [observation("good", category="Montacargas",
                            visual_features=["Equipo amarillo con mástil vertical.", "Correo persona@example.com."]),
                        observation("selfie", "unrelated", "other", category="Grúas",
                            visual_features=["Persona con camisa azul."]),
                        observation("blur", "uncertain", "unknown", visual_features=["Mascota blanca."])]
        response = parsed(observations, [field("brand", "RealBrand", "good"),
                         field("brand", "WrongBrand", "selfie"), field("model", "WrongModel", "blur"),
                         field("power", "900 kW", None, "user"), field("weight", "999 kg", "good", "user")])
        result = normalize_analysis(response, ["good", "selfie", "blur"], allowed_categories=["Montacargas", "Grúas"])
        self.assertEqual(result["relevance"], {"status": "mixed", "message": result["relevance"]["message"],
            "accepted_asset_ids": ["good"], "excluded_asset_ids": ["selfie"], "uncertain_asset_ids": ["blur"]})
        self.assertEqual(result["data"]["brand"], "RealBrand")
        self.assertEqual(result["category"], "Montacargas")
        self.assertIn("Equipo amarillo con mástil vertical", result["description"])
        for unwanted in ("WrongBrand", "WrongModel", "900", "999", "Persona", "Mascota", "persona@example.com", "GLOBAL AJENO"):
            self.assertNotIn(unwanted, str(result))
        self.assertEqual([item["asset_id"] for item in result["fields"]], ["good"])

    def test_related_plate_and_component_are_relevant_without_full_machine_photo(self):
        for kind, component in (("plate", "machine"), ("plate", "engine"), ("document", "other")):
            with self.subTest(kind=kind, component=component):
                response = parsed([observation("plate", "related", kind, category="Montacargas")],
                    plates=[{"asset_id": "plate", "component": component,
                             "readability": "partial", "transcription": "Legible machinery plate"}])
                result = normalize_analysis(response, ["plate"], allowed_categories=["Montacargas"])
                self.assertEqual(result["relevance"]["status"], "relevant")
                self.assertEqual(result["relevance"]["accepted_asset_ids"], ["plate"])
                self.assertEqual(result["plates"][0]["component"], component)

    def test_all_relevant_keeps_ambiguity_warnings_and_questions(self):
        response = parsed([observation("a", "related", "plate")])
        response.warnings = ["La serie tiene un carácter ambiguo."]
        response.questions = ["¿Puedes añadir una foto más nítida de la serie?"]
        result = normalize_analysis(response, ["a"])
        self.assertEqual(result["warnings"], response.warnings)
        self.assertEqual(result["questions"], response.questions)

    def test_categories_require_catalog_and_disagreement_never_picks_one(self):
        response = parsed([observation("a", category="Montacargas"), observation("b", category="Grúas")])
        result = normalize_analysis(response, ["a", "b"], allowed_categories=["Montacargas", "Grúas"])
        self.assertIsNone(result["category"])
        self.assertTrue(any("categorías distintas" in text for text in result["warnings"]))
        response = parsed([observation("a", category="Unknown secret category")])
        result = normalize_analysis(response, ["a"], allowed_categories=["Montacargas"])
        self.assertIsNone(result["category"])
        self.assertNotIn("Unknown secret category", str(result))

    def test_foreign_asset_is_still_invalid_even_when_classified_unrelated(self):
        with self.assertRaises(ValidationError):
            normalize_analysis(parsed([observation("foreign", "unrelated", "other")]), ["own"])

    def test_per_image_feature_count_and_length_are_bounded(self):
        response = parsed([observation("a", visual_features=["Equipo amarillo.", "Cabina cerrada.",
                           "Cucharón frontal.", "Rasgo que excede la cantidad."]),
                           observation("b", visual_features=["Texto demasiado largo " * 10, "Ruedas visibles."])])
        result = normalize_analysis(response, ["a", "b"])
        self.assertEqual(len(result["image_observations"][0]["visual_features"]), 3)
        self.assertEqual(result["image_observations"][1]["visual_features"], ["Ruedas visibles."])
        self.assertNotIn("excede la cantidad", str(result))
        self.assertNotIn("Texto demasiado largo", str(result))


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-4.1-mini")
class ImageRelevanceWorkerTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="image-relevance@example.invalid")
        self.machine = Machine.objects.create(owner=self.owner, title="Human title",
            data={"brand": "HumanBrand", "model": "HumanModel", "description": "Human description"},
            provenance={key: {"source": "user", "review": "confirmed"} for key in ("brand", "model", "description")})
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=1000000)
        Category.objects.create(name="Montacargas", slug="montacargas")
        self.asset = Asset.objects.create(machine=self.machine, kind="image", purpose="general",
            processing_status="ready", original="test/unused.jpg", preview="test/unused.jpg",
            size=1, mime_type="image/jpeg", sha256="a" * 64)

    def response(self, status):
        if status == "empty":
            return parsed([], [field("brand", "WrongBrand", str(self.asset.pk))])
        return parsed([observation(str(self.asset.pk), status, "other")],
                      [field("brand", "WrongBrand", str(self.asset.pk))])

    def test_unrelated_and_uncertain_finish_with_real_usage_and_never_search_declared_identity(self):
        for relevance in ("unrelated", "uncertain", "empty"):
            with self.subTest(relevance=relevance):
                # Give each scenario a fresh fingerprint without changing any
                # human value or authorizing more provider work.
                self.machine.revision += 1
                self.machine.save(update_fields=["revision"])
                job = enqueue_analysis(self.machine, self.owner, research=True, authorize_ai=True)
                response = SimpleNamespace(status="completed", output_parsed=self.response(relevance),
                    usage=SimpleNamespace(input_tokens=230, output_tokens=70))
                with patch("portal.processing._image_input", return_value={"type": "input_image", "image_url": "data:test"}), \
                     patch("openai.OpenAI") as provider, patch("portal.processing.research_machine") as research:
                    provider.return_value.responses.parse.return_value = response
                    self.assertTrue(process_next_job())
                research.assert_not_called()
                provider.return_value.responses.create.assert_not_called()
                job.refresh_from_db()
                self.assertEqual((job.status, job.input_tokens, job.output_tokens, job.reserved_tokens), ("completed", 230, 70, 0))
                self.assertEqual(job.result["data"], {})
                self.assertEqual(job.result["research"]["status"], "not_run")
                self.assertEqual(job.result["research"]["reason"], "image_relevance")
                self.assertEqual(job.result["usage"]["input_tokens"], 230)
                self.machine.refresh_from_db()
                self.assertEqual(self.machine.title, "Human title")
                self.assertEqual(self.machine.data["description"], "Human description")

    def test_mixed_only_passes_accepted_image_data_into_research(self):
        other = Asset.objects.create(machine=self.machine, kind="image", purpose="general",
            processing_status="ready", original="test/other.jpg", preview="test/other.jpg",
            size=1, mime_type="image/jpeg", sha256="b" * 64)
        useful, unrelated = str(self.asset.pk), str(other.pk)
        response = parsed([observation(useful, category="Montacargas", visual_features=["Equipo con mástil vertical."]),
                           observation(unrelated, "unrelated", "other")],
                          [field("power", "10 kW", useful), field("model", "SELFIE-MODEL", unrelated)])
        job = enqueue_analysis(self.machine, self.owner, research=True, authorize_ai=True)
        with patch("portal.processing._image_input", return_value={"type": "input_image", "image_url": "data:test"}), \
             patch("openai.OpenAI") as provider, patch("portal.processing.research_machine", return_value=(empty_research(), UsageTotals())) as research:
            provider.return_value.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=response,
                usage=SimpleNamespace(input_tokens=250, output_tokens=80))
            result, usage = process_analysis(job)
        research.assert_called_once()
        supplied = research.call_args.args[2]
        self.assertNotIn("SELFIE-MODEL", str(supplied))
        self.assertEqual(supplied["data"]["power"], "10 kW")
        self.assertIn("mástil vertical", result["description"])
        self.assertEqual(result["relevance"]["status"], "mixed")
        self.assertEqual((usage.input_tokens, usage.output_tokens), (250, 80))
