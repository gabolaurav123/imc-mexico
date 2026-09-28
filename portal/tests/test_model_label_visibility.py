"""Visible characters do not establish that the whole model label is visible."""
from django.test import SimpleTestCase
from openai.lib._pydantic import to_strict_json_schema

from portal.processing import MachineAnalysis, _bind_image_aliases, _merge_image_results, normalize_analysis
from portal.research import _accepted_visual_model_hint, research_identity
from portal.tests.test_partial_model_reading import reading


class ModelLabelVisibilityTests(SimpleTestCase):
    def parsed(self, visibility, model="7T-20", source="image", review="clear"):
        value = reading(f"Texto «{model}» legible en la carrocería.", model, source, review).model_dump()
        value["fields"][1]["model_label_visibility"] = visibility
        return MachineAnalysis(**value)

    def normalized(self, parsed):
        return normalize_analysis(parsed, ["photo"], allowed_categories=["Compactadores"])

    def test_hidden_or_unverified_label_is_not_an_exact_model_even_with_clear_characters(self):
        for visibility in ("partial_start", "partial_middle", "unknown", None):
            with self.subTest(visibility=visibility):
                parsed = self.parsed(visibility)
                original = parsed.model_dump()
                result = self.normalized(parsed)
                self.assertIsNone(result["data"]["model"])
                self.assertEqual(result["provenance"]["model"]["review"], "needs_review")
                self.assertEqual(result["data"]["brand"], "ACME")
                self.assertNotIn("7T-20", result["title"])
                self.assertNotIn("7T-20", result["data"]["description"])
                self.assertIn("«7T-20»", result["provenance"]["model"]["evidence"])
                self.assertEqual(research_identity(result, allowed_categories=["Compactadores"])[1], "category")
                self.assertIsNone(_accepted_visual_model_hint(result))
                merged = _merge_image_results([result], ["photo"], ["Compactadores"])
                self.assertEqual(merged["fields"], result["fields"])
                self.assertEqual(parsed.model_dump(), original)

    def test_partial_end_retains_only_a_discovery_prefix(self):
        result = self.normalized(self.parsed("partial_end", model="ZX200"))
        self.assertEqual(result["data"]["model"], "ZX200")
        self.assertEqual(result["provenance"]["model"]["review"], "needs_review")
        self.assertIsNone(research_identity(result)[0]["model"])
        self.assertEqual(_accepted_visual_model_hint(result)["value"], "ZX200")

    def test_complete_short_model_codes_remain_valid_without_any_brand_format_rule(self):
        for model in ("R2", "90", "7T-20"):
            with self.subTest(model=model):
                result = self.normalized(self.parsed("complete", model))
                self.assertEqual(result["data"]["model"], model)
                self.assertEqual(result["provenance"]["model"]["review"], "clear")
        result = self.normalized(self.parsed("complete", review="needs_review"))
        self.assertEqual(result["provenance"]["model"]["review"], "needs_review")

    def test_new_complete_flag_does_not_override_explicit_partial_evidence(self):
        parsed = self.parsed("complete")
        parsed.fields[1].evidence = "Inicio del rótulo oculto por la cabina; fragmento «7T-20»."
        result = self.normalized(parsed)
        self.assertIsNone(result["data"]["model"])
        self.assertEqual(result["provenance"]["model"]["review"], "needs_review")

    def test_historical_absence_survives_binding_serialization_and_combined_reading(self):
        parsed = reading("Rótulo «7T-20» visible.")
        self.assertNotIn("model_label_visibility", parsed.fields[1].model_dump())
        self.assertNotIn("model_label_visibility", parsed.model_dump()["fields"][1])
        bound = _bind_image_aliases(parsed, [{"alias": "photo", "asset_id": "photo"}])
        rebuilt = MachineAnalysis(**bound.model_dump())
        result = self.normalized(rebuilt)
        merged = _merge_image_results([result], ["photo"], ["Compactadores"])
        self.assertEqual(merged["data"]["model"], "7T-20")
        self.assertEqual(merged["provenance"]["model"]["review"], "clear")
        explicit_null = self.parsed(None)
        self.assertIn("model_label_visibility", explicit_null.model_dump()["fields"][1])
        self.assertIsNone(self.normalized(MachineAnalysis(**explicit_null.model_dump()))["data"]["model"])

    def test_plate_and_user_identity_keep_existing_rules_and_human_correction_wins(self):
        result = self.normalized(self.parsed(None, source="plate"))
        self.assertEqual(result["data"]["model"], "7T-20")
        self.assertEqual(result["provenance"]["model"]["review"], "clear")
        result = self.normalized(self.parsed("partial_start"))
        for meta in ({"source": "user"}, {"source": "image", "review": "confirmed"}):
            self.assertEqual(research_identity(result, {"data": {"model": "ZX-7T-20"},
                "provenance": {"model": meta}})[0]["model"], "ZX-7T-20")

    def test_provider_strict_schema_requires_nullable_visibility_on_new_responses(self):
        schema = to_strict_json_schema(MachineAnalysis)["$defs"]["ExtractedField"]
        self.assertIn("model_label_visibility", schema["required"])
        choices = schema["properties"]["model_label_visibility"]["anyOf"]
        self.assertTrue(any(choice.get("type") == "null" for choice in choices))
        self.assertIn("complete", next(choice["enum"] for choice in choices if "enum" in choice))
