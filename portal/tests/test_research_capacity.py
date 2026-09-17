"""Displacement/service-fluid volumes cannot become machine capacity."""
from copy import deepcopy

from django.core import signing
from django.test import SimpleTestCase

from portal.research import (ResearchCandidate, ResearchCandidates, SIGNING_SALT, _manifest,
    is_validated_web_field, machine_capacity_evidence, merge_research, normalize_candidates)


URL = "https://www.lectura-specs.com/en/model/construction-machinery/graders-caterpillar/14h-1005586"
TITLE = "Caterpillar 14H Specifications & Technical Data (2003-2007) | LECTURA Specs"
IDENTITY = {"brand": "CAT", "model": "14H", "serial": None}


def normalized(body, value):
    candidate = ResearchCandidate(key="capacity", value=value, scope="model", passage_index=0,
                                  matched_brand="CAT", matched_model="14H", matched_serial=None)
    return normalize_candidates(ResearchCandidates(fields=[candidate]), IDENTITY, "model",
        [{"url": URL, "title": TITLE}], body, [{"source_url": URL, "text": body}], {URL: TITLE})


class ResearchCapacityTests(SimpleTestCase):
    def test_real_receipt_displacement_is_rejected_before_signing(self):
        result = normalized("- **Cilindrada**: 5.2 litros.", "5.2 litros")
        self.assertEqual(result["fields"], [])
        self.assertEqual(result["diagnostics"]["field_rejection_counts"]["capacity"],
                         {"capacity_not_machine_capacity": 1})
        merged = merge_research({"data": {}, "provenance": {}, "fields": [], "warnings": []}, result)
        self.assertNotIn("capacity", merged["data"])

    def test_fluid_and_displacement_measurements_never_become_capacity(self):
        examples = [
            ("Engine displacement: 5.2 litres.", "5.2 litres"),
            ("Engine capacity: 5200 cc.", "5200 cc"),
            ("Capacidad del motor: 5.2 litros.", "5.2 litros"),
            ("Fuel tank capacity: 400 L.", "400 L"),
            ("Capacidad de combustible: 300 litros.", "300 litros"),
            ("Hydraulic system capacity: 40 L.", "40 L"),
            ("Capacidad de aceite: 20 litros.", "20 litros"),
            ("Coolant capacity: 15 L.", "15 L"),
            ("Capacidad de batería: 100 Ah.", "100 Ah"),
            ("Capacidad: 5.2 litros.", "5.2 litros"),
            ("Peso: 2500 kg.", "2500 kg"),
        ]
        for body, value in examples:
            with self.subTest(body=body):
                self.assertEqual(normalized(body, value)["fields"], [])

    def test_explicit_load_bucket_hopper_and_production_capacities_remain_valid(self):
        examples = [
            ("Capacidad de carga: 2500 kg.", "2500 kg"),
            ("CAPACITY: 5000 LBS.", "5000 LBS"),
            ("Capacidad del cucharón: 80 litros.", "80 litros"),
            ("Bucket capacity: 5.2 L.", "5.2 L"),
            ("Hopper capacity: 500 L.", "500 L"),
            ("Capacidad de tolva: 10 m3.", "10 m3"),
            ("Capacidad productiva: 100 t/h.", "100 t/h"),
            ("Reference Bucket Capacity: 1.6 yd3.", "Reference Bucket Capacity: 1.6 yd3"),
        ]
        for body, value in examples:
            with self.subTest(body=body):
                result = normalized(body, value)
                self.assertEqual([item["value"] for item in result["fields"]], [value])
                merged = merge_research({"data": {}, "provenance": {}, "fields": [], "warnings": []}, result)
                self.assertTrue(is_validated_web_field(merged, "capacity", value, merged["provenance"]["capacity"]))

    def test_different_row_or_document_title_cannot_supply_capacity_meaning(self):
        evidence = "Bucket capacity: 80 L; Engine displacement: 5.2 litres."
        self.assertFalse(machine_capacity_evidence("5.2 litres", evidence))
        self.assertTrue(machine_capacity_evidence("80 L", evidence))
        self.assertFalse(machine_capacity_evidence("5.2 L",
            "Título de la fuente citada: Bucket capacity for Caterpillar 14H\nFragmento citado: 5.2 L."))

    def test_previously_signed_displacement_is_rejected_without_changing_manifest(self):
        research = normalized("Bucket capacity: 5.2 litros.", "5.2 litros")
        old = deepcopy(research)
        old["fields"][0]["evidence"] = f"Título de la fuente citada: {TITLE}\nFragmento citado: - **Cilindrada**: 5.2 litros."
        # Represents a genuine legacy manifest issued before semantic checking,
        # not a forged/tampered signature. The new guard must still reject it.
        old["proof"] = signing.Signer(salt=SIGNING_SALT).sign_object(_manifest(old), compress=True)
        field = old["fields"][0]
        meta = {key: field[key] for key in ("scope", "source_url", "source_title", "source_date", "evidence")}
        meta.update(source="web", review="needs_review", component="machine")
        self.assertFalse(is_validated_web_field({"research": old}, "capacity", "5.2 litros", meta))
        meta["review"] = "confirmed"
        self.assertFalse(is_validated_web_field({"research": old}, "capacity", "5.2 litros", meta))
        self.assertEqual(old["fields"][0]["value"], "5.2 litros")
