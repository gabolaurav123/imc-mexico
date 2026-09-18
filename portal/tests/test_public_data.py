import json

from django.test import SimpleTestCase

from portal.public_data import public_json, public_projection


class PublicDataProjectionTests(SimpleTestCase):
    def test_projection_is_allowlisted_and_drops_internal_values(self):
        snapshot = {"data": {"brand": "CAT", "hours": 1200, "serial": "PRIVATE",
                              "estimate_missing_info": "sube horas", "price": "0",
                              "description": "", "location": "Por confirmar"},
                    "provenance": {"price": {"source": "valuation", "review": "needs_review"}}}
        self.assertEqual(public_projection(snapshot), {"brand": "CAT", "hours": 1200})

    def test_confirmed_owner_price_survives_and_json_has_stable_schema(self):
        snapshot = {"data": {"price": "125000", "currency": "MXN", "estimated_year_from": 2010},
                    "provenance": {"price": {"source": "user", "review": "confirmed"}}}
        self.assertEqual(public_projection(snapshot)["price"], "125000")
        exported = public_json(snapshot)
        self.assertEqual(exported["schema_version"], "public-machine-v1")
        json.dumps(exported)

    def test_identifier_embedded_in_public_text_is_removed(self):
        snapshot = {"data": {"serial": "SN-PRIVATE-77", "title": "CAT SN-PRIVATE-77",
                              "description": "Equipo SN-PRIVATE-77 listo", "brand": "CAT"}}
        projection = public_projection(snapshot)
        self.assertNotIn("description", projection)
        self.assertNotIn("title", projection)
        self.assertNotIn("SN-PRIVATE-77", public_json(snapshot, title="CAT SN-PRIVATE-77")["title"] or "")
