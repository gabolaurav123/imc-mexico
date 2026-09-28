"""Automatic readiness requires useful prose; owner copy remains the owner's."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from portal.ai_completion import complete_machine_reference, missing_fields
from portal.intake import preparation_completeness
from portal.models import AnalysisJob, Machine
from portal.research import compose_description
from portal.tests.test_ai_completion import proposal


DATA = {"brand": "Caterpillar", "model": "320D", "weight": "21000 kg", "power": "103 kW",
        "capacity": "1.2 m³", "estimated_year_from": 2006, "estimated_year_to": 2015,
        "estimate_min": 45000, "estimate_max": 90000, "estimate_currency": "USD"}
GOOD = ("Características de referencia del modelo:\n"
        "Excavadora hidráulica de orugas para excavación y carga de materiales.\n"
        "Superestructura giratoria con pluma y brazo articulados.\n"
        "Equipo de referencia para movimiento de tierras y construcción.")
AP300_REFERENCE = (
    "Pavimentadora de asfalto sobre ruedas para trabajos de extendido vial.\n"
    "Diseñada para facilitar el desplazamiento entre frentes de obra.\n"
    "Integra sistema de extendido y control operativo orientado a una colocación uniforme."
)


class DescriptionCompletenessTests(SimpleTestCase):
    def result(self, description=None):
        meta = {key: {"source": "image", "review": "clear", "component": "machine"} for key in DATA}
        for key in ("estimated_year_from", "estimated_year_to"):
            meta[key] = {"source": "web", "review": "needs_review"}
        description = description if description is not None else compose_description(DATA, meta, "Excavadoras")
        return {"category": "Excavadoras", "data": {**DATA, "description": description},
                "provenance": {**meta, "description": {"source": "system", "review": "needs_review"}}}

    def complete(self, result, parsed=None, snapshot=None):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=parsed or proposal(),
            usage=SimpleNamespace(input_tokens=100, output_tokens=60))
        reference, _ = complete_machine_reference(client, "gpt-4.1-mini", result, snapshot,
                                                   allowed_categories=["Excavadoras"])
        return client, reference

    def saved_completion(self, data, provenance=None, historical=False):
        machine = Machine(category_id=1, data=deepcopy(data), provenance=provenance or {})
        return preparation_completeness(machine, AnalysisJob(result={} if historical else {"completion": {}}))

    def test_title_specs_and_year_are_not_three_technical_sentences(self):
        result = self.result()
        self.assertEqual(len(result["data"]["description"].splitlines()), 3)
        self.assertGreater(len(result["data"]["description"]), 100)
        client, reference = self.complete(result)
        client.responses.parse.assert_called_once()
        self.assertEqual(reference["fields"]["description"], GOOD)
        self.assertEqual(reference["missing_fields"], [])
        self.assertIn("description", missing_fields(result["data"], "Excavadoras"))

    def test_rejected_short_ai_answer_does_not_mark_the_old_summary_complete(self):
        result = self.result()
        _, reference = self.complete(result, proposal(technical_lines=["Equipo para movimiento de tierras."]))
        self.assertIsNotNone(reference)
        self.assertNotIn("description", reference["fields"])
        self.assertIn("description", reference["missing_fields"])
        self.assertIn("description", self.saved_completion(result["data"])["missing_fields"])

    def test_long_identity_and_composed_numeric_reference_are_not_technical_prose(self):
        result = self.result()
        result["data"].update(brand="John Deere", model="544K", attachments="Cucharón frontal para carga de materiales.")
        for key in ("weight", "power", "capacity"):
            result["provenance"][key] = {"source": "web", "review": "needs_review"}
        result["provenance"]["attachments"] = {"source": "visual_proposal"}
        for key in ("estimated_year_from", "estimated_year_to"):
            result["provenance"][key] = {}
        result["data"]["description"] = compose_description(result["data"], result["provenance"], "Cargadores frontales")
        self.assertEqual(len(result["data"]["description"].splitlines()), 3)
        self.assertIn("description", missing_fields(result["data"], "Cargadores frontales", result["provenance"]))
        self.assertIn("description", self.saved_completion(result["data"], result["provenance"])["missing_fields"])

    def test_generation_and_saved_readiness_reject_short_or_repeated_automatic_text(self):
        for text in ("Maquinaria.", "\n".join(["Maquinaria presentada con datos disponibles."] * 3)):
            with self.subTest(text=text):
                data = {**DATA, "description": text}
                self.assertIn("description", missing_fields(data, "Excavadoras"))
                self.assertIn("description", self.saved_completion(data)["missing_fields"])

    def test_existing_three_technical_sentences_need_no_completion_call(self):
        for text in (GOOD, " ".join(GOOD.splitlines()[1:]), AP300_REFERENCE,
                     "\n".join("• " + line for line in AP300_REFERENCE.splitlines())):
            with self.subTest(text=text):
                result = self.result(text)
                result["provenance"]["description"] = {"source": "ai_reference"}
                client, reference = self.complete(result)
                client.responses.parse.assert_not_called()
                self.assertIsNone(reference)
                self.assertEqual(missing_fields(result["data"], "Excavadoras"), [])
                self.assertEqual(self.saved_completion(result["data"])["missing_fields"], [])

    def test_owner_written_or_confirmed_description_is_preserved_and_ready(self):
        for meta in ({"source": "user"}, {"source": "ai_reference", "review": "confirmed"}):
            with self.subTest(meta=meta):
                result = self.result("Descripción propia.")
                result["provenance"]["description"] = meta
                client, reference = self.complete(result, snapshot=result)
                client.responses.parse.assert_not_called()
                self.assertIsNone(reference)
                self.assertEqual(missing_fields(result["data"], "Excavadoras", result["provenance"]), [])
                self.assertEqual(self.saved_completion(result["data"], result["provenance"])["missing_fields"], [])

    def test_historical_share_contract_is_unchanged(self):
        self.assertEqual(self.saved_completion({**DATA, "description": "Maquinaria."}, historical=True), {})
