"""Signed references to model A cannot silently follow an identity refresh to B."""
from copy import deepcopy

from django.test import TestCase, override_settings

from portal.services import (apply_analysis_automatically, public_web_references,
                             web_research_for_provenance)
from portal.tests import test_web_autofill as fixtures


@override_settings(PRIVATE_S3_BUCKET="")
class StaleWebIdentityTests(TestCase):
    def setUp(self):
        fixtures.WebAutofillTests.setUp(self)
        self.old_job = fixtures.WebAutofillTests.job(self, fixtures.WebAutofillTests.result(self))
        self.machine, _ = apply_analysis_automatically(self.machine, self.owner, self.old_job, self.machine.revision)
        self.machine.provenance["model"] = {"source": "image", "review": "clear", "component": "machine",
            "asset_id": str(self.asset.pk), "analysis_id": str(self.old_job.pk)}
        self.machine.save()

    def refresh_model(self):
        # No power/weight candidate at all in this new reading.
        result = {"data": {"model": "430E"}, "provenance": {"model": {
            "source": "image", "review": "clear", "component": "machine", "asset_id": str(self.asset.pk)}},
            "fields": [], "plates": [], "warnings": [], "research": {"status": "disabled"}}
        job = fixtures.WebAutofillTests.job(self, result)
        self.machine, summary = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        return job, summary

    def displayed_snapshot(self):
        return {"data": deepcopy(self.machine.data), "provenance": deepcopy(self.machine.provenance),
                "web_research": web_research_for_provenance(self.machine.provenance)}

    def test_refresh_removes_old_web_specs_before_composing_and_preserves_signed_history(self):
        before = self.displayed_snapshot()
        self.assertEqual(len(public_web_references(before)), 2)
        original_result = deepcopy(self.old_job.result)
        job, summary = self.refresh_model()
        self.assertEqual(self.machine.data["model"], "430E")
        self.assertEqual(set(summary["invalidated_fields"]), {"power", "weight"})
        for key in ("power", "weight"):
            self.assertNotIn(key, self.machine.data)
            self.assertNotIn(key, self.machine.provenance)
        for old_value in ("70 kW", "8000 kg", "420F2"):
            self.assertNotIn(old_value, self.machine.data["description"])
        self.assertEqual(public_web_references(self.displayed_snapshot()), [])
        self.old_job.refresh_from_db()
        self.assertEqual(self.old_job.result, original_result)
        self.assertEqual(len(public_web_references(before)), 2)  # Old immutable identity still matches its own proof.
        revision = self.machine.revision
        self.machine, second = apply_analysis_automatically(self.machine, self.owner, job, revision)
        self.assertEqual(self.machine.revision, revision)
        self.assertEqual(second["invalidated_fields"], summary["invalidated_fields"])

    def test_confirmed_web_values_human_description_and_plate_readings_survive(self):
        self.machine.provenance["power"]["review"] = "confirmed"
        self.machine.provenance["weight"] = {"source": "plate", "review": "clear", "component": "machine",
            "asset_id": str(self.asset.pk), "analysis_id": str(self.old_job.pk)}
        self.machine.data["description"] = "Descripción editada por su propietario."
        self.machine.provenance["description"] = {"source": "user", "review": "confirmed"}
        self.machine.save()
        self.refresh_model()
        self.assertEqual(self.machine.data["power"], "70 kW")
        self.assertEqual(self.machine.provenance["power"]["review"], "confirmed")
        self.assertEqual(self.machine.data["weight"], "8000 kg")
        self.assertEqual(self.machine.provenance["weight"]["source"], "plate")
        self.assertEqual(self.machine.data["description"], "Descripción editada por su propietario.")
        # Retaining a human-confirmed value does not relabel its old URL as a reference for model B.
        self.assertEqual(public_web_references(self.displayed_snapshot()), [])

    def test_export_rejects_stale_identity_even_when_old_manifest_is_authentic(self):
        snapshot = self.displayed_snapshot()
        snapshot["data"]["model"] = "430E"
        self.assertEqual(public_web_references(snapshot), [])
        snapshot["data"]["model"] = "420F2"
        snapshot["data"]["brand"] = "CAT"  # A known brand alias is not a different identity.
        self.assertEqual(len(public_web_references(snapshot)), 2)
