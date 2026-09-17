"""Prepared commercial text must not copy private IDs through technical values."""
from copy import deepcopy

from django.test import SimpleTestCase

from portal.research import compose_description, identifier_key


FIELDS = ("front_tire_size", "rear_tire_size", "mast_tilt", "load_tire_tread", "manufacturer",
          "manufacturer_address", "voltage", "lift_height", "load_center", "battery_weight",
          "battery_capacity", "fork_length", "power", "weight", "capacity")


class DescriptionIdentifierPrivacyTests(SimpleTestCase):
    def test_technical_values_cannot_reintroduce_a_private_serial_or_vin(self):
        for identifier_field in ("serial", "vin"):
            for key in FIELDS:
                for source in ("plate", "user", "web"):
                    with self.subTest(identifier=identifier_field, field=key, source=source):
                        data = {identifier_field: "PRIVATE-FORK1234", key: "Dato ｐｒｉｖａｔｅ fork １２３４",
                                "weight": "4500 kg"} if key != "weight" else {
                                    identifier_field: "PRIVATE-FORK1234", key: "Dato ｐｒｉｖａｔｅ fork １２３４"}
                        meta = {key: {"source": source, "review": "clear"}}
                        original = deepcopy((data, meta))
                        description = compose_description(data, meta, "Montacargas")
                        self.assertNotIn(identifier_key(data[identifier_field]), identifier_key(description))
                        self.assertNotIn("Dato", description)
                        self.assertEqual((data, meta), original)

    def test_external_and_source_match_exclusions_also_filter_fields_and_identity(self):
        for exclusions, meta in (("PRIVATE-FORK1234", {}), (["PRIVATE-FORK1234"], {}),
                                 ((), {"weight": {"matched_serial": "PRIVATE-FORK1234"}})):
            with self.subTest(exclusions=exclusions, source=meta):
                data = {"brand": "PRIVATE-FORK1234", "model": "PRIVATE-FORK1234", "manufacturer_address": "Houston PRIVATE-FORK1234"}
                provenance = {key: {"source": "plate", "review": "clear"} for key in data} | meta
                description = compose_description(data, provenance, "Montacargas", private_identifiers=exclusions)
                self.assertNotIn("PRIVATE-FORK1234", description)
                self.assertEqual(description, "Montacargas. Fotografías disponibles para identificar sus características.")

    def test_legitimate_manufacturer_address_and_literal_technical_values_remain(self):
        data = {"serial": "PRIVATE-FORK1234", "brand": "Caterpillar", "model": "2EC25",
                "manufacturer_address": "Houston, USA", "manufacturer": "Fabricante de prueba Inc.",
                "front_tire_size": "21x7x15", "mast_tilt": "Rearward 6 deg", "battery_weight": "MIN 1800 lb / MAX 2200 lb"}
        provenance = {key: {"source": "plate", "review": "clear"} for key in data}
        description = compose_description(data, provenance, "Montacargas")
        for key, value in data.items():
            if key != "serial":
                self.assertIn(value, description)
        self.assertNotIn(data["serial"], description)
        self.assertNotIn("país de fabricación", description.lower())
        self.assertNotIn("ubicación", description.lower())

    def test_private_category_text_does_not_leak_into_heading(self):
        description = compose_description({"serial": "PRIVATE-FORK1234"}, {}, "PRIVATE-FORK1234")
        self.assertNotIn("PRIVATE-FORK1234", description)
