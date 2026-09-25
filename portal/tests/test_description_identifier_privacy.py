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

    def test_summary_keeps_identity_but_leaves_plate_details_in_structured_fields(self):
        data = {"serial": "PRIVATE-FORK1234", "brand": "Caterpillar", "model": "2EC25",
                "manufacturer_address": "Houston, USA", "manufacturer": "Fabricante de prueba Inc.",
                "front_tire_size": "21x7x15", "mast_tilt": "Rearward 6 deg", "battery_weight": "MIN 1800 lb / MAX 2200 lb"}
        provenance = {key: {"source": "plate", "review": "clear"} for key in data}
        description = compose_description(data, provenance, "Montacargas")
        self.assertIn("Caterpillar 2EC25", description)
        self.assertNotIn(data["serial"], description)
        for value in (data["manufacturer_address"], data["manufacturer"], data["front_tire_size"],
                      data["mast_tilt"], data["battery_weight"]):
            self.assertNotIn(value, description)
        self.assertNotIn("país de fabricación", description.lower())
        self.assertNotIn("ubicación", description.lower())

    def test_private_category_text_does_not_leak_into_heading(self):
        description = compose_description({"serial": "PRIVATE-FORK1234"}, {}, "PRIVATE-FORK1234")
        self.assertNotIn("PRIVATE-FORK1234", description)

    def test_public_summary_uses_four_essentials_and_skips_photo_prose(self):
        data = {"brand": "Volvo", "model": "EC210B", "weight": "21 300 kg", "power": "107 kW",
                "digging_depth": "6,7 m", "maximum_reach_ground": "9,9 m", "capacity": "1,0 m³",
                "manufacturer_address": "Houston, USA"}
        provenance = {key: {"source": "web", "review": "needs_review"} for key in data}
        provenance["brand"] = {"source": "image", "review": "clear"}
        provenance["model"] = {"source": "image", "review": "clear"}
        description = compose_description(data, provenance, "Excavadoras",
                                          visual_description="Excavadora amarilla con suciedad y pintura gastada.")
        self.assertLessEqual(len(description), 650)
        self.assertEqual(description.splitlines()[0], "Excavadora Volvo EC210B.")
        self.assertIn("Peso: 21 300 kg", description)
        self.assertIn("Profundidad máxima de excavación: 6,7 m", description)
        self.assertNotIn("1,0 m³", description)  # Fifth priority is structured-only.
        self.assertNotIn("Houston", description)
        self.assertNotIn("suciedad", description)

    def test_compact_summary_distinguishes_model_references_and_approximate_age_without_review_instructions(self):
        data = {"brand": "Volvo", "model": "EC210B", "weight": "21 300 kg", "power": "107 kW",
                "estimated_year_from": "2003", "estimated_year_to": "2009",
                "estimated_year_basis": "EVIDENCIA INTERNA: periodo documentado; año de la unidad por confirmar.",
                "visible_components": "Cabina\nBrazo articulado", "applications": "Usos sugeridos, sujetos a verificación: Excavación de zanjas"}
        provenance = {key: {"source": "user", "review": "confirmed"} for key in data}
        provenance["power"] = {"source": "web", "review": "needs_review"}
        provenance["visible_components"] = {"source": "visual_proposal", "review": "needs_review"}
        provenance["applications"] = {"source": "visual_proposal", "review": "needs_review"}
        original = deepcopy((data, provenance))
        description = compose_description(data, provenance, "Excavadoras")
        self.assertEqual(len(description.splitlines()), 4)
        self.assertLessEqual(len(description), 650)
        self.assertIn("Datos principales: Peso: 21 300 kg; Características de referencia del modelo: Potencia: 107 kW.", description)
        self.assertIn("Año aproximado: 2003–2009.", description)
        self.assertIn("Aplicaciones sugeridas: Excavación de zanjas", description)
        for hidden in ("por confirmar", "por revisar", "requieren comprobación", "sujetos a verificación", "EVIDENCIA INTERNA"):
            self.assertNotIn(hidden, description)
        self.assertEqual((data, provenance), original)

    def test_family_description_stays_approximate_without_private_basis_and_exact_model_has_priority(self):
        data = {'brand':'CAT','model':None,'model_family':'320D','serial':'PRIVATE-SERIAL-320',
                'estimated_year_from':2006,'estimated_year_to':2020,
                'estimated_year_basis':'PRIVATE-SERIAL-320 https://private.example.com/internal por confirmar'}
        provenance = {key:{'source':'family_reference','review':'needs_review'} for key in data}
        provenance['brand']={'source':'image','review':'clear'}
        original = deepcopy((data, provenance))
        text = compose_description(data, provenance, 'Excavadoras')
        self.assertEqual(text.splitlines()[0], 'Excavadora CAT · familia 320D.')
        self.assertIn('Año aproximado: 2006–2020.', text)
        for private in ('PRIVATE-SERIAL-320','https://','private.example.com','por confirmar'):
            self.assertNotIn(private, text)
        self.assertEqual((data, provenance), original)
        data['model']='320D L'
        provenance['model']={'source':'user','review':'confirmed'}
        exact = compose_description(data, provenance, 'Excavadoras')
        self.assertEqual(exact.splitlines()[0], 'Excavadora CAT 320D L.')
        self.assertNotIn('familia', exact)
        data['model']=None
        data['model_family']=data['serial']
        self.assertNotIn(data['serial'], compose_description(data, provenance, 'Excavadoras'))
