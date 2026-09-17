"""Visual proposals remain bound to equipment photos and never certify operation."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from portal.processing import (MachineAnalysis, VISUAL_ASSESSMENT_LABELS, _merge_image_results,
                               enqueue_analysis, normalize_analysis, process_next_job,
                               visual_assessment_fields)
from portal.tests import test_image_bindings as fixtures
from portal.tests.test_image_relevance import field, observation, parsed


def assessment(**changes):
    value = dict(usage_condition="Usada", preservation_condition="Aceptable",
        preservation_notes="Pintura desgastada y óxido superficial en el bastidor.",
        visible_defects=["Óxido superficial en el bastidor"],
        visible_components=["Mástil y horquillas visibles"], attachments=["Horquillas instaladas"],
        applications=["Movimiento de cargas paletizadas"])
    value.update(changes)
    return value


def visual(asset="photo", *, value=None, relevance="machinery", kind="machine", fields=()):
    return parsed([observation(asset, relevance, kind, category="Montacargas",
                              visual_assessment=assessment() if value is None else value)], fields)


def normalize(response, ids=("photo",)):
    return normalize_analysis(response, list(ids), allowed_categories=["Montacargas"])


class VisualAssessmentNormalizationTests(SimpleTestCase):
    def test_strict_schema_includes_nullable_assessment_with_closed_enums(self):
        from openai.lib._pydantic import to_strict_json_schema
        schema = to_strict_json_schema(MachineAnalysis)
        self.assertIn("visual_assessment", schema["$defs"]["ImageObservation"]["required"])
        assessment_schema = schema["$defs"]["VisualAssessment"]
        self.assertEqual(set(assessment_schema["required"]), set(assessment_schema["properties"]))
        self.assertFalse(assessment_schema["additionalProperties"])
        self.assertNotIn("Reacondicionada", assessment_schema["properties"]["usage_condition"]["enum"])

    def test_machine_photo_generates_reviewable_fields_and_never_operating_claim(self):
        response = visual(fields=[field("operating_status", "Funciona perfectamente", "photo"),
                                  field("condition", "Reacondicionada", "photo")])
        result = normalize(response)
        self.assertEqual(result["data"]["usage_condition"], "Usada")
        self.assertEqual(result["data"]["preservation_condition"], "Aceptable")
        self.assertEqual(result["data"]["operating_status"], "Pendiente de confirmar")
        self.assertNotIn("condition", result["data"])
        self.assertNotIn("Funciona perfectamente", str(result))
        self.assertTrue(result["data"]["applications"].startswith("Usos sugeridos, sujetos a verificación:"))
        for key in VISUAL_ASSESSMENT_LABELS:
            with self.subTest(key=key):
                meta = result["provenance"][key]
                self.assertEqual((meta["source"], meta["review"], meta["asset_id"]),
                                 ("visual_proposal", "needs_review", "photo"))
                self.assertTrue(meta["evidence"])
                self.assertEqual(result["data"][key], visual_assessment_fields(result)[key]["value"])

    def test_plate_document_or_unrelated_never_assess_equipment_condition(self):
        for kind, relevance in (("plate", "related"), ("document", "related"),
                                 ("machine", "unrelated"), ("unknown", "uncertain")):
            with self.subTest(kind=kind, relevance=relevance):
                result = normalize(visual(kind=kind, relevance=relevance))
                self.assertFalse(set(result["data"]) & set(VISUAL_ASSESSMENT_LABELS))
                self.assertIsNone(result["image_observations"][0]["visual_assessment"])

    def test_model_flat_fields_cannot_bypass_absent_assessment_or_legacy_observation(self):
        for obs in ([observation("photo")], [{"asset_id": "photo", "kind": "machine"}]):
            with self.subTest(obs=obs):
                result = normalize(parsed(obs, [field("preservation_condition", "Excelente", "photo")]))
                self.assertFalse(set(result["data"]) & set(VISUAL_ASSESSMENT_LABELS))

    def test_missing_or_unsafe_justification_downgrades_condition_but_keeps_safe_components(self):
        for notes in (None, "Serie PRIVATE123; contacto test@example.invalid.", "Funciona perfectamente.",
                      "Equipo reacondicionado con mantenimiento certificado."):
            with self.subTest(notes=notes):
                result = normalize(visual(value=assessment(usage_condition="Aparentemente nueva",
                    preservation_condition="Excelente", preservation_notes=notes,
                    attachments=["Compatible con Caterpillar 420F2", "Horquillas instaladas"],
                    visible_defects=["Sin defectos", "Óxido visible"],
                    applications=["Capacidad de 4 toneladas", "Movimiento de materiales"])))
                self.assertEqual(result["data"]["usage_condition"], "Por confirmar")
                self.assertEqual(result["data"]["preservation_condition"], "Por confirmar")
                self.assertNotIn("preservation_notes", result["data"])
                self.assertEqual(result["data"]["attachments"], "Horquillas instaladas")
                self.assertEqual(result["data"]["visible_defects"], "Óxido visible")
                self.assertNotIn("PRIVATE123", str(result))
                self.assertNotIn("toneladas", result["data"]["applications"])

    def test_mixed_content_uses_only_accepted_photo_and_real_evidence(self):
        response = parsed([
            observation("good", visual_assessment=assessment()),
            observation("bad", "unrelated", "other", visual_assessment=assessment(
                preservation_notes="Texto personal ajeno", visible_components=["Mascota blanca"]))])
        result = normalize(response, ["bad", "good"])
        self.assertEqual(result["relevance"]["status"], "mixed")
        self.assertNotIn("Texto personal", str(result))
        self.assertNotIn("Mascota", str(result))
        self.assertTrue(all(meta["asset_id"] == "good" for key, meta in result["provenance"].items()
                            if key in VISUAL_ASSESSMENT_LABELS))

    def test_merge_keeps_complementary_observations_but_disputed_conditions_need_confirmation(self):
        first = normalize(visual("a"), ["a"])
        second = normalize(visual("b", value=assessment(preservation_condition="Deficiente",
            preservation_notes="Abolladuras en la carrocería.", visible_components=["Cabina visible"])), ["b"])
        for readings in ([first, second], [second, first]):
            with self.subTest(first=readings[0]["image_observations"][0]["asset_id"]):
                result = _merge_image_results(readings, ["a", "b"], ["Montacargas"])
                self.assertEqual(result["data"]["preservation_condition"], "Por confirmar")
                self.assertEqual(result["data"]["usage_condition"], "Usada")
                self.assertIn("Cabina visible", result["data"]["visible_components"])
                self.assertIn("horquillas", result["data"]["visible_components"])
                self.assertEqual(set(result["visual_assessment_support"]["visible_components"]), {"a", "b"})
                self.assertEqual(result["data"]["attachments"].count("Horquillas instaladas"), 1)
                for key in VISUAL_ASSESSMENT_LABELS:
                    self.assertEqual(visual_assessment_fields(result)[key]["value"], result["data"][key])

    def test_assessment_lists_and_text_are_bounded_and_do_not_promote_specs(self):
        result = normalize(visual(value=assessment(preservation_notes="x" * 401,
            visible_components=["Horquillas visibles", "Cabina visible", "Motor de 300 kW", "Cuarta observación"],
            attachments=["a" * 141])))
        self.assertEqual(result["data"]["visible_components"], "Horquillas visibles; Cabina visible")
        self.assertNotIn("attachments", result["data"])
        self.assertNotIn("power", result["data"])


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-4.1-mini")
class VisualAssessmentWorkerTests(TestCase):
    def setUp(self):
        fixtures.ImageMessageBindingTests.setUp(self)

    def test_per_photo_binding_retains_visual_proposal_without_new_calls_or_clearing_plate_facts(self):
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True, research=False)
        responses = [SimpleNamespace(status="completed", output_parsed=visual("image_001"),
                                    usage=SimpleNamespace(input_tokens=400, output_tokens=200)),
                     SimpleNamespace(status="completed", output_parsed=visual("image_001", kind="plate", relevance="related",
                        fields=[field("power", "10 kW", "image_001", "plate")]),
                        usage=SimpleNamespace(input_tokens=400, output_tokens=200))]
        with patch("portal.processing._image_input", return_value={"type": "input_image", "image_url": "data:test"}), \
             patch("openai.OpenAI") as provider:
            provider.return_value.responses.parse.side_effect = responses
            self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(provider.return_value.responses.parse.call_count, 2)
        self.assertEqual((job.input_tokens, job.output_tokens), (800, 400))
        self.assertEqual(job.result["data"]["power"], "10 kW")
        self.assertEqual(job.result["provenance"]["usage_condition"]["asset_id"], job.asset_ids[0])
        self.assertIsNone(job.result["image_observations"][1]["visual_assessment"])
        self.assertEqual(job.result["data"]["operating_status"], "Pendiente de confirmar")
