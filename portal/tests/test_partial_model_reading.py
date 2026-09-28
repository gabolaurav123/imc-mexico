"""An occluded label fragment is neither an exact model nor a family prefix."""
from django.test import SimpleTestCase

from portal.processing import MachineAnalysis, normalize_analysis
from portal.research import _accepted_visual_model_hint, research_identity


def reading(evidence, model="7T-20", source="image", review="clear"):
    return MachineAnalysis(
        title=f"Compactador ACME {model}", description=f"Compactador ACME {model}.",
        category="Compactadores", warnings=[], questions=[], plates=[],
        fields=[
            dict(key="brand", label="Marca", value="ACME", source="image", review="clear",
                 asset_id="photo", component="machine", evidence="ACME"),
            dict(key="model", label="Modelo", value=model, source=source, review=review,
                 asset_id="photo", component="machine", evidence=evidence),
        ],
        image_observations=[dict(asset_id="photo", kind="machine", relevance="machinery",
                                 category="Compactadores")],
    )


class PartialModelReadingTests(SimpleTestCase):
    def normalize(self, parsed):
        return normalize_analysis(parsed, ["photo"], allowed_categories=["Compactadores"])

    def test_explicit_occlusion_overrides_clear_without_completing_or_reusing_the_fragment(self):
        for evidence in (
            "Inicio del rótulo oculto por la cabina; fragmento «7T-20».",
            "Extremo izquierdo del modelo tapado; texto «7T-20».",
            "Rótulo parcialmente oculto: «7T-20».",
            "Modelo incompleto: «7T-20».",
            "Model label partially occluded: «7T-20».",
            "Left edge of the label is cropped; fragment «7T-20».",
        ):
            with self.subTest(evidence=evidence):
                result = self.normalize(reading(evidence))
                self.assertIsNone(result["data"]["model"])
                self.assertEqual(result["provenance"]["model"]["review"], "needs_review")
                self.assertEqual(result["fields"][1]["evidence"], evidence)
                self.assertEqual(result["data"]["brand"], "ACME")
                self.assertNotIn("7T-20", result["title"])
                self.assertNotIn("7T-20", result["data"]["description"])
                self.assertEqual(research_identity(result, allowed_categories=["Compactadores"])[1], "category")
                self.assertIsNone(_accepted_visual_model_hint(result))

    def test_existing_doubtful_suffix_cannot_be_used_as_a_discovery_prefix(self):
        result = self.normalize(reading("El modelo muestra «7T-20». Inicio del rótulo oculto.", review="needs_review"))
        # The discovery boundary must also protect saved pre-fix readings.
        result["fields"][1]["value"] = "7T-20"
        self.assertIsNone(_accepted_visual_model_hint(result))

    def test_legible_beginning_with_only_doubtful_suffix_remains_a_hint_not_an_exact_model(self):
        result = self.normalize(reading("Rótulo «ZX200» parcial; sufijo no confirmable.", model="ZX200"))
        self.assertEqual(result["data"]["model"], "ZX200")
        self.assertEqual(result["provenance"]["model"]["review"], "needs_review")
        self.assertIsNone(research_identity(result)[0]["model"])
        self.assertEqual(_accepted_visual_model_hint(result)["value"], "ZX200")
        self.assertNotIn("ZX200", result["title"])

    def test_short_complete_models_and_unrelated_serial_occlusion_are_not_rejected(self):
        for model in ("R2", "90", "7T-20"):
            for evidence in (
                f"Modelo «{model}» completo; ambos extremos visibles.",
                f"Modelo «{model}» completo; inicio de la serie oculto.",
                f"Rótulo «{model}» completo, sin caracteres ocultos.",
            ):
                with self.subTest(model=model, evidence=evidence):
                    result = self.normalize(reading(evidence, model=model))
                    self.assertEqual(result["data"]["model"], model)
                    self.assertEqual(result["provenance"]["model"]["review"], "clear")
                    self.assertEqual(research_identity(result)[0]["model"], model)

    def test_human_identity_wins_over_an_occluded_photograph(self):
        evidence = "Inicio del rótulo oculto; fragmento «7T-20»."
        result = self.normalize(reading(evidence))
        for source in ("user", "image"):
            snapshot = {"data": {"model": "ZX-7T-20"},
                        "provenance": {"model": {"source": source, "review": "confirmed"}}}
            self.assertEqual(research_identity(result, snapshot)[0]["model"], "ZX-7T-20")
