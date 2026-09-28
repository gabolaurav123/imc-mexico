"""Punctuation may change between reads; printed numbers and conditions may not."""
from django.test import SimpleTestCase

from portal.dual_measurements import canonical_dual_measurement, equivalent_dual_measurements, parse_dual_measurement
from portal.processing import normalize_analysis
from portal.tests.test_plate_enrichment import plate_analysis


class DualMeasurementTests(SimpleTestCase):
    def test_both_printed_values_survive_canonical_punctuation(self):
        for key, original, canonical in (
            ("weight", "8240 lb; 3740 kg", "8240 lb / 3740 kg"),
            ("capacity", "500 lbs ; 227 kg", "500 lbs / 227 kg"),
            ("lift_height", "189 in; 4800 mm", "189 in / 4800 mm"),
            ("lift_height", "C: 189 in; 4800 mm", "C: 189 in / 4800 mm"),
        ):
            with self.subTest(key=key):
                self.assertEqual(canonical_dual_measurement(key, original), canonical)
                self.assertTrue(equivalent_dual_measurements(key, original, canonical))

    def test_equivalence_preserves_both_numbers_and_field_unit_meaning(self):
        self.assertTrue(equivalent_dual_measurements("weight", "8240 lb / 3740 kg", "3740 kg; 8240 lbs"))
        self.assertTrue(equivalent_dual_measurements("lift_height", "C: 189 in / 4800 mm", "189 in; 4800 mm"))
        for key, left, right in (
            ("weight", "8240 lb / 3740 kg", "8240 lb; 3750 kg"),
            ("weight", "8240 lb / 3740 kg", "3740 kg"),
            ("capacity", "500 lb / 227 kg", "500 lb / 0.227 t"),
            ("lift_height", "C: 189 in / 4800 mm", "A: 189 in / 4800 mm"),
            ("lift_height", "C: 189 in / 4800 mm", "Z: 189 in / 4800 mm"),
            ("capacity", "189 in / 4800 mm", "189 in; 4800 mm"),
            ("power", "8240 lb / 3740 kg", "8240 lb; 3740 kg"),
        ):
            with self.subTest(key=key, right=right):
                self.assertFalse(equivalent_dual_measurements(key, left, right))

    def test_qualified_or_multicondition_values_remain_opaque_and_unchanged(self):
        for key, value in (
            ("weight", "MAX 8240 lb; 3740 kg"),
            ("weight", "MIN 8240 lb / 3740 kg"),
            ("capacity", "2250 kg; 1950 kg"),
            ("capacity", "500 lb at 24 in; 227 kg at 600 mm"),
            ("capacity", "2250 kg a 600 mm; 1950 kg a 760 mm"),
            ("capacity", "500 lb / 227 kg / 300 kg"),
            ("lift_height", "MAX 189 in; 4800 mm"),
            ("lift_height", "A: 189 in; 4800 mm"),
        ):
            with self.subTest(value=value):
                self.assertIsNone(parse_dual_measurement(key, value))
                self.assertEqual(canonical_dual_measurement(key, value), value)

    def test_plate_normalization_keeps_transcription_evidence_and_conditional_capacity(self):
        values = {"weight": "8240 lb; 3740 kg", "lift_height": "C: 189 in; 4800 mm",
                  "capacity": "2250 kg a 600 mm; 1950 kg a 760 mm"}
        fields = [dict(key=key, label=key, value=value, source="plate", review="clear", component="machine",
                       asset_id="plate-image", evidence=f"{key}: {value}") for key, value in values.items()]
        transcription = "\n".join(f"{key}: {value}" for key, value in values.items())
        result = normalize_analysis(plate_analysis(fields=fields, plates=[dict(asset_id="plate-image", component="machine",
            readability="clear", transcription=transcription)]), ["plate-image"])
        self.assertEqual(result["data"]["weight"], "8240 lb / 3740 kg")
        self.assertEqual(result["data"]["lift_height"], "C: 189 in / 4800 mm")
        self.assertEqual(result["data"]["capacity"], values["capacity"])
        self.assertEqual(result["plates"][0]["transcription"], transcription)
        self.assertEqual(result["provenance"]["weight"]["evidence"], "weight: 8240 lb; 3740 kg")
