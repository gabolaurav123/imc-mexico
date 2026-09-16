"""Literal evidence checks only: no provider calls, fixtures or database access."""
from django.test import SimpleTestCase

from portal.research_evidence import (
    explicit_manufacturing_origin, has_conflicting_unit_reference,
)


class UnitReferenceEvidenceTests(SimpleTestCase):
    def conflicting(self, evidence, serial="UNIT123", *, brand="HESSEN", model="016-9020"):
        return has_conflicting_unit_reference(evidence, serial, brand=brand, model=model)

    def test_product_series_is_not_a_different_unit_identifier(self):
        phrases = ("La serie HESSEN 016-9020 pesa 90 kg.",
                   "HESSEN: serie 016-9020, peso 90 kg.",
                   "La serie de compactadores HESSEN 016-9020 pesa 90 kg.",
                   "La serie de equipos HESSEN 016-9020 pesa 90 kg.",
                   "HESSEN 016-9020: peso 90 kg.")
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertFalse(self.conflicting(phrase))
                self.assertFalse(self.conflicting(phrase, serial=None))
        self.assertFalse(self.conflicting("La serie CAT 420F2 pesa 90 kg.", brand="Caterpillar", model="420F2"))

    def test_strong_serial_labels_never_borrow_the_commercial_model_exception(self):
        for label in ("Número de serie", "Núm. de serie", "N.º de serie", "N° de serie", "N de serie",
                      "Serial number", "Serial", "S/N", "S. N.", "SN", "PIN", "VIN", "Seriennummer",
                      "Numéro de série", "Numero di serie"):
            with self.subTest(label=label):
                self.assertTrue(self.conflicting(f"{label}: 016-9020. HESSEN 016-9020 pesa 90 kg."))
                self.assertFalse(self.conflicting(f"{label}: UNIT123. HESSEN 016-9020 pesa 90 kg."))

    def test_unknown_and_other_units_are_rejected_even_if_requested_serial_is_elsewhere(self):
        for tail in ("OTHER999", "UNIT1234", "XUNIT123", "UNIT123-4", "UNIT123/4",
                     "de OTHER999", "desconocida", "ilegible", "[unreadable]", ""):
            with self.subTest(tail=tail):
                self.assertTrue(self.conflicting(f"Se buscó UNIT123. HESSEN 016-9020 serie {tail}: peso 90 kg."))
        self.assertTrue(self.conflicting("Serial UNIT123; serial OTHER999; peso 90 kg."))
        self.assertTrue(self.conflicting("Serie HESSEN 016-9020. S/N OTHER999: peso 90 kg."))
        self.assertTrue(self.conflicting("Serial UNIT123: peso 90 kg.", serial=None))

    def test_literal_formatting_is_allowed_without_accepting_longer_identifiers(self):
        for serial in ("UNIT123", "UNIT-123", "UNIT 123", "U N I T 1 2 3", "unit123"):
            with self.subTest(serial=serial):
                self.assertFalse(self.conflicting(f"HESSEN 016-9020 serie {serial}: peso 90 kg."))
        self.assertTrue(self.conflicting("Serie HESSEN 016-90201: peso 90 kg."))

    def test_denied_match_is_not_a_conflicting_unit_and_does_not_establish_exact_match(self):
        # False is deliberately only a veto result. The existing normalizer's
        # serial_match_denied guard must still prevent exact-unit attribution.
        for denial in ("No encontré datos de serie UNIT123", "Sin coincidencia para la serie UNIT123",
                       "No exact match for serial UNIT123", "Serial UNIT123 not found"):
            with self.subTest(denial=denial):
                self.assertFalse(self.conflicting(denial + ". HESSEN 016-9020 pesa 90 kg."))
        self.assertTrue(self.conflicting("Serial OTHER999 not found. HESSEN 016-9020 pesa 90 kg."))


class ManufacturingOriginEvidenceTests(SimpleTestCase):
    def test_recognizes_explicit_labels_in_six_languages_without_translating_values(self):
        examples = (("Made in Germany", "Germany"), ("Manufactured in China", "China"),
                    ("Country of origin: Japan", "Japan"), ("Fabricado en México", "México"),
                    ("País de fabricación: Alemania", "Alemania"), ("País de origen: China", "China"),
                    ("Hergestellt in Deutschland", "Deutschland"),
                    ("Gefertigt in Österreich", "Österreich"), ("Herstellungsland: Schweiz", "Schweiz"),
                    ("Fabriqué en France", "France"), ("Fabriquée au Canada", "Canada"),
                    ("Pays de fabrication: Italie", "Italie"), ("Fabbricato in Italia", "Italia"),
                    ("Prodotta in Germania", "Germania"), ("Paese di fabbricazione: Italia", "Italia"),
                    ("Fabricado no Brasil", "Brasil"), ("Fabricada na China", "China"),
                    ("País de fabricação: Portugal", "Portugal"), ("País de origem: Brasil", "Brasil"))
        for phrase, value in examples:
            with self.subTest(phrase=phrase):
                self.assertTrue(explicit_manufacturing_origin("HESSEN 016-9020. " + phrase + ".", value))
        self.assertTrue(explicit_manufacturing_origin("MADE   IN：\n Germany", "germany"))

    def test_rejects_unproven_translations_headquarters_slogans_and_unrelated_countries(self):
        examples = (("Made in Germany", "Alemania"), ("Hergestellt in Deutschland", "Germany"),
                    ("Fabriqué en Allemagne", "Alemania"), ("Made in China", "Germany"),
                    ("Made in China. Headquarters: Germany", "Germany"),
                    ("Sede: Alemania. HESSEN ist Qualität.", "Alemania"),
                    ("Distribuido desde Alemania", "Alemania"), ("Fabricado en. Alemania es la sede.", "Alemania"),
                    ("Made in Germanyland", "Germany"), ("Origin: Germany", "Germany"),
                    ("Made in unknown", "unknown"), ("País de origen: Deutschland", "Alemania"))
        for phrase, value in examples:
            with self.subTest(phrase=phrase, value=value):
                self.assertFalse(explicit_manufacturing_origin(phrase, value))

    def test_negation_uncertainty_and_questions_do_not_prove_origin(self):
        examples = (("Not made in Germany", "Germany"), ("No fabricado en Alemania", "Alemania"),
                    ("No evidence: Made in Germany", "Germany"), ("Possibly made in Germany", "Germany"),
                    ("Made in Germany is not confirmed", "Germany"), ("Made in Germany or China", "Germany"),
                    ("Made in Germany?", "Germany"), ("País de origen: China, no confirmado", "China"),
                    ("Nicht hergestellt in Deutschland", "Deutschland"),
                    ("Hergestellt in Deutschland, nicht bestätigt", "Deutschland"),
                    ("Pas fabriqué en France", "France"), ("Non fabbricato in Italia", "Italia"),
                    ("Não fabricado no Brasil", "Brasil"), ("Ejemplo: Fabricado en Alemania", "Alemania"))
        for phrase, value in examples:
            with self.subTest(phrase=phrase):
                self.assertFalse(explicit_manufacturing_origin(phrase, value))
        self.assertTrue(explicit_manufacturing_origin("Not made in China. Made in Germany.", "Germany"))
        self.assertFalse(explicit_manufacturing_origin("Not made in China. Made in Germany.", "China"))

    def test_invalid_inputs_fail_closed(self):
        for evidence, value in ((None, "China"), ("Made in China", None), ("Made in China", ""),
                                ("Made in China", "x" * 81), ("x" * 12001, "China")):
            with self.subTest(value=value):
                self.assertFalse(explicit_manufacturing_origin(evidence, value))
        self.assertTrue(has_conflicting_unit_reference(None, "UNIT123"))
