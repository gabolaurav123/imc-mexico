"""A saved response must reflect server-side invalidation of automatic prices."""
from django.test import TestCase, override_settings

from portal.models import Machine
from portal.tests import test_commercial_autofill as fixtures


@override_settings(SECURE_SSL_REDIRECT=False, STAFF_MFA_REQUIRED=False)
class SaveStateTests(TestCase):
    estimate_result = fixtures.CommercialAutofillTests.estimate_result
    job = fixtures.CommercialAutofillTests.job
    apply = fixtures.CommercialAutofillTests.apply

    def setUp(self):
        fixtures.CommercialAutofillTests.setUp(self)
        self.apply(self.job(self.estimate_result()))
        self.client.force_login(self.user)
        self.url = f"/api/maquinarias/{self.machine.pk}/guardar/"

    def save(self, data):
        response = self.client.post(self.url, {"revision": self.machine.revision, "data": data},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.machine.refresh_from_db()
        return response.json()

    def test_response_includes_persisted_state_after_identity_invalidates_automatic_price(self):
        self.assertIn("estimate_suggested_price", self.machine.data)
        self.assertNotIn("price", self.machine.data)
        response = self.save({"model": "DIFFERENT MODEL"})
        state = response["machine"]
        self.assertEqual(response["revision"], state["revision"])
        self.assertEqual(state["data"], self.machine.data)
        self.assertEqual(state["provenance"], self.machine.provenance)
        self.assertEqual(state["valuation"], {})
        self.assertEqual(state["data"]["model"], "DIFFERENT MODEL")
        for key in ("estimate_min", "estimate_max", "estimate_currency", "estimate_suggested_price", "price"):
            self.assertNotIn(key, state["data"])

    def test_response_keeps_manual_zero_and_blank_and_stale_request_cannot_replace_them(self):
        response = self.save({"model": "DIFFERENT MODEL", "price": "0", "currency": "EUR",
                              "visible_defects": None})
        state = response["machine"]
        self.assertEqual(state["data"]["price"], 0)
        self.assertEqual(state["data"]["currency"], "EUR")
        self.assertIsNone(state["data"]["visible_defects"])
        self.assertEqual(state["provenance"]["price"]["source"], "user")
        self.assertEqual(state["provenance"]["price"]["review"], "confirmed")
        self.assertTrue(state["provenance"]["price"]["source_date"])
        stale = self.client.post(self.url, {"revision": response["revision"] - 1,
            "data": {"price": "9999", "visible_defects": "stale"}}, content_type="application/json")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(Machine.objects.get(pk=self.machine.pk).data, state["data"])

    def test_analysis_response_keeps_rejected_price_diagnostics_internal(self):
        result = self.estimate_result()
        diagnostics = {"rejected_candidates": [{"url": "https://example.com/rejected-unit", "reason": "sale_type_not_literal"}]}
        result["valuation"]["diagnostics"] = diagnostics
        job = self.job(result)
        response = self.client.get(f"/api/analisis/{job.pk}/")
        self.assertEqual(response.status_code, 200)
        visible = response.json()["result"]["valuation"]
        self.assertNotIn("diagnostics", visible)
        self.assertEqual(visible["fields"], result["valuation"]["fields"])
        self.assertNotIn("rejected-unit", response.content.decode())
        job.refresh_from_db()
        self.assertEqual(job.result["valuation"]["diagnostics"], diagnostics)
