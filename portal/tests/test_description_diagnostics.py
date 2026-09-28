"""Explain rejected technical prose privately without saving its unsafe text."""
from copy import deepcopy

from django.test import SimpleTestCase

from portal.ai_completion import is_validated_ai_reference, merge_machine_reference, normalize_reference
from portal.public_data import public_projection
from portal.tests.test_ai_completion import DATA, IDENTITY, proposal, reference


class DescriptionDiagnosticsTests(SimpleTestCase):
    def test_complete_description_records_counts_without_private_warning(self):
        accepted = reference()
        self.assertEqual(accepted["diagnostics"]["description"], {
            "status": "accepted", "received_lines": 3, "considered_lines": 3,
            "accepted_lines": 3, "rejection_counts": {},
        })
        self.assertTrue(is_validated_ai_reference(accepted))
        result = merge_machine_reference({"data": {}, "provenance": {}}, accepted)
        self.assertFalse(result.get("warnings"))

    def test_rejection_reasons_count_without_retaining_raw_or_private_prose(self):
        private = "PRIVATE-SERIAL-492"
        lines = ["Característica demasiado extensa " * 10,
                 f"Equipo identificado con serie {private} y cabina cerrada.",
                 "Potencia nominal del motor de 999 kW para la configuración descrita.",
                 "La configuración puede variar según la versión y sus accesorios."]
        rejected = normalize_reference(proposal(technical_lines=lines), IDENTITY, DATA,
                                       "Excavadoras", ["Excavadoras"], [private])
        diagnostics = rejected["diagnostics"]["description"]
        self.assertEqual(diagnostics, {
            "status": "omitted", "received_lines": 4, "considered_lines": 4, "accepted_lines": 0,
            "rejection_counts": {"overlong": 1, "unsafe_or_private": 1, "numeric_unverified": 1,
                                 "generic": 1, "too_few_lines": 1},
        })
        self.assertNotIn("description", rejected["fields"])
        for text in (private, *lines):
            self.assertNotIn(text, str(rejected))
        result = merge_machine_reference({"data": {}, "provenance": {}}, rejected)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("4 líneas recibidas y 0 conservadas", result["warnings"][0])
        self.assertIn("cifras sin respaldo", result["warnings"][0])
        self.assertNotIn(private, result["warnings"][0])
        merge_machine_reference(result, rejected)
        self.assertEqual(len(result["warnings"]), 1)
        public = public_projection(result)
        self.assertNotIn("warnings", public)
        self.assertNotIn("diagnostics", public)
        self.assertNotIn("Descripción técnica incompleta", str(public))

    def test_structure_duplicate_and_empty_failures_are_distinguishable_and_bounded(self):
        short = reference(technical_lines=["Cabina.", "Orugas.", "Pluma."])
        self.assertEqual(short["diagnostics"]["description"]["rejection_counts"], {"structure": 1})
        self.assertEqual(short["diagnostics"]["description"]["accepted_lines"], 3)
        invalid = reference(technical_lines=["", None])
        self.assertEqual(invalid["diagnostics"]["description"]["rejection_counts"],
                         {"empty_or_invalid": 2, "too_few_lines": 1})
        repeated = reference(technical_lines=[proposal().technical_lines[0]] * 200)
        self.assertEqual(repeated["diagnostics"]["description"], {
            "status": "omitted", "received_lines": 100, "considered_lines": 4, "accepted_lines": 1,
            "rejection_counts": {"duplicate": 3, "too_few_lines": 1},
        })

    def test_human_description_and_invalid_proof_do_not_emit_rejection_warning(self):
        rejected = reference(technical_lines=[])
        result = merge_machine_reference({"data": {"description": "Texto del dueño"}, "provenance": {}}, rejected,
            {"data": {"description": "Texto del dueño"}, "provenance": {"description": {"source": "user"}}})
        self.assertFalse(result.get("warnings"))
        self.assertEqual(result["data"]["description"], "Texto del dueño")
        tampered = deepcopy(rejected)
        tampered["diagnostics"]["description"]["received_lines"] = 99
        self.assertFalse(is_validated_ai_reference(tampered))
        self.assertEqual(merge_machine_reference({}, tampered), {})
