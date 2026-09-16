"""Reading aids explain existing values without inventing or leaking data."""
from copy import deepcopy
import json

from django.test import SimpleTestCase

from portal.sheet_details import build_sheet_details


class SheetDetailsTests(SimpleTestCase):
    def test_present_values_are_preserved_without_conversions_specs_or_mutation(self):
        data = {"power": "4.8 kW / 6.5 HP", "weight": "90 Kg", "vibration_frequency": "4200 VPM",
                "centrifugal_force": "13 kN", "compaction_depth": "30 CM", "dimensions": None, "capacity": ""}
        provenance = {key: {"source": "plate", "review": "clear"} for key in data}
        original = deepcopy((data, provenance))
        items = build_sheet_details(data, provenance)
        self.assertEqual([item["value"] for item in items], list(data.values())[:5])
        self.assertEqual({item["scope"] for item in items}, {"general_context"})
        self.assertEqual({item["reading_status"] for item in items}, {"Leído en placa"})
        self.assertNotIn("70 Hz", json.dumps(items))
        self.assertNotIn("HESSEN", json.dumps(items))
        self.assertEqual((data, provenance), original)

    def test_conflicted_and_confirmed_readings_keep_their_actual_status(self):
        data = {"power": "4.5 kW", "weight": "90 kg", "capacity": "5 L"}
        meta = {"power": {"source": "plate", "review": "needs_review", "review_reason": "conflicting_reading"},
                "weight": {"source": "plate", "review": "confirmed"}, "capacity": {"source": "web", "review": "needs_review"}}
        items = {item["key"]: item for item in build_sheet_details(data, meta)}
        self.assertIn("conflicto", items["power"]["reading_status"])
        self.assertIn("Confirmado", items["weight"]["reading_status"])
        self.assertIn("por revisar", items["capacity"]["reading_status"])
        self.assertEqual(items["power"]["value"], "4.5 kW")
        self.assertNotIn("certificada", json.dumps(items))

    def test_private_identifiers_notes_and_untrusted_links_are_not_reused(self):
        data = {"power": "70 kW PRIVATE1234", "weight": "90 kg", "serial": "PRIVATE1234",
                "notes": "PRIVATE NOTE", "location": "PRIVATE LOCATION", "contact_public": "person@example.invalid"}
        meta = {"weight": {"source": "web", "review": "needs_review", "evidence": "PRIVATE EVIDENCE",
                           "source_url": "https://untrusted.example.com/PRIVATE1234", "asset_id": "PRIVATE ASSET",
                           "analysis_id": "PRIVATE JOB"}}
        items = build_sheet_details(data, meta)
        self.assertEqual([item["key"] for item in items], ["weight"])
        serialized = json.dumps(items)
        for forbidden in ("PRIVATE", "untrusted", "person@example.invalid"):
            self.assertNotIn(forbidden, serialized)
        self.assertTrue(items[0]["reference"]["url"].startswith("https://www.husqvarnaconstruction.com/"))
        items[0]["reference"]["url"] = "changed locally"
        self.assertNotEqual(build_sheet_details({"weight": "90 kg"})[0]["reference"]["url"], "changed locally")

    def test_missing_malformed_or_non_numeric_values_do_not_create_empty_cards(self):
        self.assertEqual(build_sheet_details(None), [])
        self.assertEqual(build_sheet_details({}), [])
        for value in (None, "", "No identificado", True, [], {}, float("nan"), float("inf"),
                      "<script>90</script>", "90 owner@example.com", "https://example.com/90", "1" * 161):
            with self.subTest(value=value):
                self.assertEqual(build_sheet_details({"power": value}), [])
        self.assertEqual(build_sheet_details({"power": 0})[0]["value"], "0")
