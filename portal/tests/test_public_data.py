import json

from django.test import SimpleTestCase

from portal.public_data import public_json, public_projection


class PublicDataProjectionTests(SimpleTestCase):
    def test_previous_price_exports_fixed_caveat_and_original_context_without_private_basis(self):
        from portal.ai_completion import PREVIOUS_PRICE_LABEL, PREVIOUS_PRICE_NOTE
        snapshot = {"data": {"estimate_min": "15000", "estimate_max": "45000", "estimate_currency": "USD",
            "estimate_market": "Estados Unidos", "estimate_date": "2026-09-27", "location_country": "México",
            "estimate_basis": "PRIVATE BASIS AND SOURCE", "estimate_reference_note": "INJECTED NOTE"},
            "provenance": {"estimate_min": {"source": "ai_reference", "label": PREVIOUS_PRICE_LABEL,
                "evidence": "PRIVATE EVIDENCE"}}}
        data = public_json(snapshot)["data"]
        self.assertEqual(data["estimate_reference_note"], PREVIOUS_PRICE_NOTE)
        self.assertEqual(data["estimate_market"], "Estados Unidos")
        self.assertEqual(data["estimate_date"], "2026-09-27")
        self.assertEqual(data["location_country"], "México")
        self.assertNotIn("PRIVATE", json.dumps(data))
        self.assertNotIn("INJECTED", json.dumps(data))
        snapshot["data"].pop("estimate_max")
        data = public_projection(snapshot)
        for key in ("estimate_reference_note", "estimate_market", "estimate_date"):
            self.assertNotIn(key, data)

    def test_market_context_cannot_expose_private_serial(self):
        snapshot = {"data": {"serial": "SECRET-SERIAL", "estimate_min": "100", "estimate_max": "200",
            "estimate_currency": "USD", "estimate_market": "SECRET-SERIAL mercado"}}
        self.assertNotIn("estimate_market", public_projection(snapshot))

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
