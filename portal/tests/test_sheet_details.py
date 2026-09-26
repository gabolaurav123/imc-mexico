"""Reading aids explain existing values without inventing or leaking data."""
from copy import deepcopy
import json

from django.test import SimpleTestCase

from portal.sheet_details import build_sheet_details, build_technical_summary, finished_sheet_data


class SheetDetailsTests(SimpleTestCase):
    def test_finished_copy_omits_workflow_values_without_rewriting_defects_or_draft(self):
        data = {"model": "Pendiente", "condition": "unknown", "hours": 0,
                "description": "Fuga hidráulica visible. Potencia por confirmar. Cabina cerrada.",
                "location_city": "La Paz", "power": float("nan")}
        original = deepcopy(data)
        copy = finished_sheet_data(data)
        self.assertNotIn("model", copy)
        self.assertNotIn("condition", copy)
        self.assertNotIn("power", copy)
        self.assertEqual(copy["hours"], 0)
        self.assertIn("Fuga hidráulica visible.", copy["description"])
        self.assertIn("Cabina cerrada.", copy["description"])
        self.assertNotIn("Potencia", copy["description"])
        self.assertEqual(data["description"], original["description"])

    def test_technical_summary_is_bounded_enriched_and_never_copies_private_identifiers(self):
        data = {"description": "Equipo hidráulico con cabina cerrada.", "power": "100 kW", "weight": "20 t",
                "capacity": "1 m³", "fuel": "Diésel", "serial": "PRIVATE1234"}
        summary = build_technical_summary(data)
        self.assertEqual(len(summary), 4)
        self.assertIn("Potencia: 100 kW", summary)
        self.assertIn("Peso operativo: 20 t", summary)
        self.assertTrue(all(len(line) <= 145 for line in summary))
        data["description"] = "Identificación PRIVATE1234"
        self.assertNotIn("PRIVATE1234", " ".join(build_technical_summary(data)))
        self.assertEqual(build_technical_summary({}), [])
        self.assertEqual(build_technical_summary({"description": "Pendiente de confirmar"}), [])

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
        self.assertEqual(items[0]["reference"], {})
        compact = build_sheet_details({"weight": "90 kg"}, category="Compactadores")
        self.assertTrue(compact[0]["reference"]["url"].startswith("https://www.husqvarnaconstruction.com/"))
        compact[0]["reference"]["url"] = "changed locally"
        self.assertNotEqual(build_sheet_details({"weight": "90 kg"}, category="Compactadores")[0]["reference"]["url"], "changed locally")

    def test_compactor_sources_are_not_attached_to_forklifts_or_unknown_categories(self):
        data = {"weight": "4500 kg", "power": "15 kW", "capacity": "2500 kg", "dimensions": "3 m"}
        for category in (None, "", "Montacargas", "Excavadoras", "Otra maquinaria"):
            with self.subTest(category=category):
                items = build_sheet_details(data, category=category)
                self.assertEqual(len(items), 4)
                self.assertTrue(all(item["reference"] == {} for item in items))
                self.assertNotIn("Husqvarna", json.dumps(items))
                self.assertNotIn("Wacker", json.dumps(items))

    def test_missing_malformed_or_non_numeric_values_do_not_create_empty_cards(self):
        self.assertEqual(build_sheet_details(None), [])
        self.assertEqual(build_sheet_details({}), [])
        for value in (None, "", "No identificado", True, [], {}, float("nan"), float("inf"),
                      "<script>90</script>", "90 owner@example.com", "https://example.com/90", "1" * 161):
            with self.subTest(value=value):
                self.assertEqual(build_sheet_details({"power": value}), [])
        self.assertEqual(build_sheet_details({"power": 0})[0]["value"], "0")
