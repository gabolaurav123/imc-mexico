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
        self.assertIn("price", self.machine.data)
        response = self.save({"model": "DIFFERENT MODEL"})
        state = response["machine"]
        self.assertEqual(response["revision"], state["revision"])
        self.assertEqual(state["data"], self.machine.data)
        self.assertEqual(state["provenance"], self.machine.provenance)
        self.assertEqual(state["valuation"], {})
        self.assertEqual(state["data"]["model"], "DIFFERENT MODEL")
        for key in ("estimate_min", "estimate_max", "estimate_currency", "price"):
            self.assertNotIn(key, state["data"])

    def test_response_keeps_manual_zero_and_blank_and_stale_request_cannot_replace_them(self):
        response = self.save({"model": "DIFFERENT MODEL", "price": "0", "currency": "EUR",
                              "visible_defects": None})
        state = response["machine"]
        self.assertEqual(state["data"]["price"], "0")
        self.assertEqual(state["data"]["currency"], "EUR")
        self.assertIsNone(state["data"]["visible_defects"])
        self.assertEqual(state["provenance"]["price"], {"source": "user", "review": "confirmed"})
        stale = self.client.post(self.url, {"revision": response["revision"] - 1,
            "data": {"price": "9999", "visible_defects": "stale"}}, content_type="application/json")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(Machine.objects.get(pk=self.machine.pk).data, state["data"])
