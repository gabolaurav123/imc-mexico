"""Field meaning guards: no network, database, translation or guessed values."""
from django.test import SimpleTestCase
from unittest.mock import patch

from portal.research import is_validated_web_field, merge_research
from portal.research_field_values import is_valid_research_field_value
from portal.tests.test_research import IDENTITY, fact, normalized, vision


class FuelValueTests(SimpleTestCase):
    def test_explicit_fuel_names_and_catalogue_aliases_are_preserved(self):
        for value in ("Diésel", "DIESEL", "diesel fuel", "gasóleo", "gas oil", "Biodiesel", "HVO100",
                      "ULSD", "diesel #2", "Gasolina", "gasoline", "petrol", "gasolina sin plomo",
                      "unleaded petrol", "gas", "Gas natural", "CNG", "GNC", "GNL", "LNG", "GLP",
                      "LPG", "Gas L.P.", "propano", "butane", "Hidrógeno", "ethanol", "queroseno",
                      "Eléctrico", "electric", "electricity", "battery", "baterías", "battery electric"):
            with self.subTest(value=value):
                self.assertTrue(is_valid_research_field_value("fuel", value))

    def test_explicit_combinations_and_parenthetical_aliases_are_allowed(self):
        for value in ("Diésel / eléctrico", "Diesel-electric", "diesel–electric", "gasolina + GLP",
                      "Gasolina y gas natural", "diesel and electric", "gas / gasoline / LPG",
                      "Gas natural (GNC)", "LPG (propane)", "Híbrido (diésel / eléctrico)",
                      "Hybrid (diesel-electric)", "  DIÉSEL  ", "Diesel."):
            with self.subTest(value=value):
                self.assertTrue(is_valid_research_field_value("fuel", value))

    def test_economy_claim_is_not_a_fuel_even_when_it_contains_a_fuel_keyword(self):
        for value in (
            "Modo Económico que reduce el consumo de combustible hasta en un 14% respecto a modelos anteriores",
            "Modo Económico que reduce el consumo de combustible hasta en un14% ...",
            "Diesel engine reduces fuel consumption by 14%", "Diésel de bajo consumo",
            "Gasolina con mayor rendimiento", "ahorra diesel", "diesel / ahorro del 14%",
            "Diesel (14% more efficient)", "el motor funciona con diésel", "Fuel efficient diesel",
            "100% eléctrico y más eficiente", "diesel. Save 14%", "electric with zero emissions",
        ):
            with self.subTest(value=value):
                self.assertFalse(is_valid_research_field_value("fuel", value))

    def test_missing_negated_and_non_fuel_values_are_rejected(self):
        for value in (None, False, 0, [], {}, "", " ", "No diésel", "not diesel", "sin gasolina",
                      "desconocido", "por confirmar", "no encontrado", "hybrid", "Tier 4 Final",
                      "70 kW", "diesel efficiency", "diesel /", "/ diesel", "diesel // electric",
                      "diesel (unknown)", "gasolina: economía", "<script>diesel</script>"):
            with self.subTest(value=value):
                self.assertFalse(is_valid_research_field_value("fuel", value))

    def test_unrelated_fields_are_outside_this_guard(self):
        for key, value in (("power", "70 kW"), ("description", "Modo económico disponible"),
                           ("country_of_origin", "Deutschland"), ("weight", None)):
            with self.subTest(key=key):
                self.assertTrue(is_valid_research_field_value(key, value))

    def test_real_normalizer_rejects_cited_marketing_but_keeps_cited_diesel(self):
        for value, accepted in (
            ("Modo Económico que reduce el consumo de combustible hasta en un 14%", False),
            ("Diésel", True),
        ):
            with self.subTest(value=value):
                evidence = f"Caterpillar 420F2: {value}."
                result = normalized([fact(key="fuel", value=value, evidence=evidence)],
                                    identity=IDENTITY, text=evidence)
                if accepted:
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual([(field["key"], field["value"]) for field in result["fields"]],
                                     [("fuel", value)])
                    self.assertNotIn("invalid_field_value", result["diagnostics"]["rejection_counts"])
                else:
                    self.assertEqual(result["fields"], [])
                    self.assertEqual(result["diagnostics"]["rejection_counts"], {"invalid_field_value": 1})


class PowerMeaningTests(SimpleTestCase):
    def test_fuel_names_are_not_power_but_numeric_ratings_remain_unchanged(self):
        for value in ("LP", "LPG", "Gas L.P.", "Diésel", "Electric", "Gasolina / GLP"):
            with self.subTest(value=value):
                self.assertFalse(is_valid_research_field_value("power", value))
                self.assertTrue(is_valid_research_field_value("fuel", value))
        for value in ("70 kW", "93 hp", "4.8 kW / 6.5 HP", "Potencia neta 70 kW", "70"):
            with self.subTest(value=value):
                self.assertTrue(is_valid_research_field_value("power", value))

    def test_cited_lp_is_kept_as_fuel_and_cannot_become_power(self):
        evidence = "Toyota 8FGCU25: TYPE LP."
        identity = {"brand": "Toyota", "model": "8FGCU25", "serial": None}
        fields = [fact(key=key, value="LP", evidence=evidence,
                       matched_brand="Toyota", matched_model="8FGCU25")
                  for key in ("power", "fuel")]
        result = normalized(fields, identity=identity, text=evidence)
        self.assertEqual([(field["key"], field["value"]) for field in result["fields"]], [("fuel", "LP")])
        self.assertEqual(result["diagnostics"]["field_rejection_counts"], {"power": {"invalid_field_value": 1}})

    def test_previously_signed_fuel_as_power_is_not_reapplied_or_exportable(self):
        evidence = "Caterpillar 420F2: combustible LP."
        with patch("portal.research.is_valid_research_field_value", return_value=True):
            legacy = normalized([fact(value="LP", evidence=evidence)], text=evidence)
        field = legacy["fields"][0]
        meta = {**field, "source": "web", "review": "needs_review"}
        self.assertFalse(is_validated_web_field({"research": legacy}, "power", "LP", meta))
        self.assertNotIn("power", merge_research(vision(), legacy)["data"])
