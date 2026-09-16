"""A different numeric reading of the same pixels needs explicit review."""
from copy import deepcopy

from django.test import TestCase

from portal.models import Asset
from portal.services import apply_analysis_automatically, save_draft
from portal.tests import test_plate_completion as fixtures


class ConflictingPlateReadingsTests(TestCase):
    def setUp(self):
        fixtures.PlateCompletionTests.setUp(self)

    def meta(self, *args, **kwargs):
        return fixtures.PlateCompletionTests.meta(self, *args, **kwargs)

    def job(self, **changes):
        job = fixtures.PlateCompletionTests.job(self, **changes)
        job.result["plates"] = [{"asset_id": str(self.asset.pk), "component": "machine", "readability": "clear",
                                 "transcription": "Serie de prueba: " + str(changes.get("serial", ""))}]
        job.save(update_fields=["result"])
        return job

    def apply(self, job):
        self.machine, summary = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        return summary

    def test_conflicting_numeric_fields_keep_old_values_pending_and_leave_automatic_description(self):
        old = {"power": "4.5 kW", "serial": "TEST-00123", "compaction_depth": "30 cm"}
        for key, value in old.items():
            self.machine.data[key] = value
            self.machine.provenance[key] = self.meta(value, self.prior.pk)
        self.machine.save()
        summary = self.apply(self.job(power="4.6 kW / 6.3 HP", serial="TEST-00823", compaction_depth="350 MM",
                                     model="NEW-MODEL"))
        self.assertEqual(set(summary["conflicting_fields"]), set(old))
        for key, value in old.items():
            self.assertEqual(self.machine.data[key], value)
            self.assertEqual(self.machine.provenance[key]["review"], "needs_review")
            self.assertEqual(self.machine.provenance[key]["review_reason"], "conflicting_reading")
            self.assertEqual(summary["field_reasons"][key], "conflicting_reading")
            self.assertNotIn(value, self.machine.data["description"])
            self.assertNotIn("350", str(self.machine.provenance[key]))
        self.assertEqual(self.machine.data["model"], "NEW-MODEL")
        for value in ("4.6", "6.3", "350", "TEST-00823"):
            self.assertNotIn(value, self.machine.data["description"])
        # Repeating the old reading does not erase an already observed conflict.
        self.apply(self.job(power="4.5 kW", serial="TEST-00123", compaction_depth="30 cm"))
        self.assertEqual(self.machine.provenance["power"]["review"], "needs_review")

    def test_case_and_whitespace_only_differences_are_not_conflicts(self):
        self.machine.data["power"] = "4.8 kW / 6.5 HP"
        self.machine.provenance["power"] = self.meta("4.8 kW / 6.5 HP", self.prior.pk)
        self.machine.save()
        summary = self.apply(self.job(power=" 4.8KW/6.5hp "))
        self.assertNotIn("power", summary.get("conflicting_fields", []))
        self.assertIn("power", summary["applied_fields"])
        self.assertEqual(self.machine.provenance["power"]["review"], "clear")

    def test_new_photograph_can_refresh_but_human_correction_stays_authoritative(self):
        self.asset = Asset.objects.create(machine=self.machine, kind="image", purpose="plate", processing_status="ready",
            sha256="b" * 64, original="test/new-plate.jpg", size=1, mime_type="image/jpeg")
        summary = self.apply(self.job(power="4.8 kW / 6.5 HP"))
        self.assertIn("power", summary["applied_fields"])
        self.assertEqual(self.machine.data["power"], "4.8 kW / 6.5 HP")
        self.machine = save_draft(self.machine, self.owner, {"data": {"power": "4.9 kW"}}, self.machine.revision)
        before = deepcopy(self.machine.provenance["power"])
        self.apply(self.job(power="4.2 kW"))
        self.assertEqual(self.machine.data["power"], "4.9 kW")
        self.assertEqual(self.machine.provenance["power"], before)
