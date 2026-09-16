"""A better plate reading completes a draft without erasing the owner's edits."""
import uuid

from django.test import TestCase

from portal.models import AnalysisJob, Asset, Consent, Machine, User
from portal.services import (apply_analysis_automatically, automatic_application_snapshot,
                             detected_plate_asset_ids, review_submission, save_draft, snapshot, submit_machine)
from portal.views import sheet_context


class PlateCompletionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="plate-completion@example.invalid", is_test=True)
        self.machine = Machine.objects.create(owner=self.owner, title="Fotografía de una etiqueta",
            data={"power": "4.5 kW", "description": "Metal y tornillos."})
        self.asset = Asset.objects.create(machine=self.machine, kind="image", purpose="general",
            processing_status="ready", sha256="a" * 64, original="test/plate.jpg", size=1, mime_type="image/jpeg")
        self.prior = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, fingerprint=uuid.uuid4().hex, status="completed")
        self.machine.provenance = {
            "title": {"source": "visual_proposal", "review": "needs_review", "analysis_id": str(self.prior.pk)},
            "description": {"source": "system", "review": "needs_review", "analysis_id": str(self.prior.pk)},
            "power": self.meta("Potencia: 4.5 kW", self.prior.pk),
        }
        self.machine.save()
        Consent.objects.create(user=self.owner, machine=self.machine, kind="ai", granted=True)

    def meta(self, evidence, analysis_id=None):
        result = {"source": "plate", "review": "clear", "component": "machine",
                  "asset_id": str(self.asset.pk), "evidence": evidence}
        if analysis_id:
            result["analysis_id"] = str(analysis_id)
        return result

    def job(self, **changes):
        values = {"title": "Compactadora de placa de prueba", "power": "4.8 kW / 6.5 HP",
                  "vibration_frequency": "4200 VPM", "centrifugal_force": "13 kN",
                  "compaction_depth": "30 cm", "country_of_origin": "País de prueba",
                  "description": "Compactadora con especificaciones leídas en la placa."}
        values.update(changes)
        provenance = {key: self.meta(f"{key}: {value}") for key, value in values.items()}
        for key in ("title", "description"):
            provenance[key] = {"source": "system", "review": "needs_review"}
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, fingerprint=uuid.uuid4().hex, status="completed",
            auto_apply=True, asset_ids=[str(self.asset.pk)],
            application_snapshot=automatic_application_snapshot(self.machine),
            result={"data": values, "provenance": provenance, "plates": [], "fields": []})

    def apply(self, job):
        self.machine, summary = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        return summary

    def test_new_reading_completes_plate_specs_and_flags_conflicting_same_image_numbers(self):
        job = self.job()
        summary = self.apply(job)
        self.assertEqual(self.machine.title, "Compactadora de placa de prueba")
        self.assertEqual(self.machine.data["power"], "4.5 kW")
        self.assertEqual(self.machine.provenance["power"]["review"], "needs_review")
        self.assertEqual(summary["field_reasons"]["power"], "conflicting_reading")
        self.assertNotIn("tornillos", self.machine.data["description"])
        for key in ("vibration_frequency", "centrifugal_force", "compaction_depth", "country_of_origin"):
            self.assertIn(key, summary["applied_fields"])
            self.assertEqual(self.machine.provenance[key]["analysis_id"], str(job.pk))
        visible = {field["label"]: field["value"] for field in sheet_context(self.machine)["extra_fields"]}
        self.assertEqual(visible["Frecuencia de vibración"], "4200 VPM")
        self.assertEqual(visible["Fuerza centrífuga"], "13 kN")
        self.assertEqual(visible["Profundidad de compactación"], "30 cm")
        self.assertNotIn("location", self.machine.data)
        self.assertEqual(self.machine.status, "draft")
        self.assertFalse(self.machine.versions.exists())

    def test_user_changes_title_and_power_during_analysis_are_preserved(self):
        job = self.job()
        self.machine = save_draft(self.machine, self.owner,
            {"title": "Título del propietario", "data": {"power": "5 kW", "location": "Ubicación declarada"}}, self.machine.revision)
        self.apply(job)
        self.assertEqual(self.machine.title, "Título del propietario")
        self.assertEqual(self.machine.data["power"], "5 kW")
        self.assertEqual(self.machine.data["location"], "Ubicación declarada")
        self.assertEqual(self.machine.data["centrifugal_force"], "13 kN")

    def test_explicit_clear_or_confirmation_during_analysis_is_preserved(self):
        for clear in (True, False):
            with self.subTest(clear=clear):
                self.machine.data["power"] = "4.5 kW"
                self.machine.provenance["power"] = self.meta("Potencia: 4.5 kW", self.prior.pk)
                self.machine.save()
                job = self.job()
                value = "" if clear else "4.5 kW"
                self.machine = save_draft(self.machine, self.owner,
                    {"data": {"power": value}, "provenance": {"power": {"source": "user", "review": "confirmed"}}}, self.machine.revision)
                self.apply(job)
                self.assertEqual(self.machine.data["power"], value)
                self.assertEqual(self.machine.provenance["power"]["review"], "confirmed")

    def test_later_analysis_prevents_an_older_result_from_overwriting_again(self):
        older = self.job(power="4.8 kW")
        newer = self.job(power="4.5 kW")
        self.apply(newer)
        self.apply(older)
        self.assertEqual(self.machine.data["power"], "4.5 kW")
        self.assertEqual(self.machine.provenance["power"]["analysis_id"], str(newer.pk))

    def test_null_and_uncertain_readings_do_not_erase_existing_values(self):
        job = self.job(power=None)
        job.result["provenance"]["power"]["review"] = "not_identifiable"
        job.result["data"]["country_of_origin"] = "Alemania"
        job.result["provenance"]["country_of_origin"]["review"] = "needs_review"
        job.save(update_fields=["result"])
        self.apply(job)
        self.assertEqual(self.machine.data["power"], "4.5 kW")
        self.assertNotIn("country_of_origin", self.machine.data)

    def test_legacy_snapshot_cannot_replace_existing_ai_readings(self):
        job = self.job()
        job.application_snapshot.pop("refresh_fields")
        job.save(update_fields=["application_snapshot"])
        self.apply(job)
        self.assertEqual(self.machine.title, "Fotografía de una etiqueta")
        self.assertEqual(self.machine.data["power"], "4.5 kW")

    def test_repeated_application_never_reinserts_values_after_a_user_clear(self):
        job = self.job()
        self.apply(job)
        self.machine = save_draft(self.machine, self.owner,
            {"data": {"power": "", "vibration_frequency": ""}}, self.machine.revision)
        revision = self.machine.revision
        self.apply(job)
        self.assertEqual(self.machine.data["power"], "")
        self.assertEqual(self.machine.data["vibration_frequency"], "")
        self.assertEqual(self.machine.revision, revision)

    def test_detected_plate_stays_private_in_snapshot_approval_and_preview(self):
        self.asset.public_authorized = True
        self.asset.save(update_fields=["public_authorized"])
        job = self.job()
        job.result["image_observations"] = [{"asset_id": str(self.asset.pk), "kind": "plate"}]
        job.result["plates"] = [{"asset_id": str(self.asset.pk), "component": "machine", "readability": "clear"}]
        job.save(update_fields=["result"])
        version = snapshot(self.machine, self.owner)
        self.assertEqual(version.data["private_plate_asset_ids"], [str(self.asset.pk)])
        self.assertEqual(version.data["public_asset_ids"], [])
        self.assertEqual(list(sheet_context(self.machine, version, public=True)["assets"]), [])
        self.assertEqual(sheet_context(self.machine)["assets"][0].purpose, "plate")
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.purpose, "general")
        self.owner.advertiser_status = "approved"
        self.owner.save(update_fields=["advertiser_status"])
        submission = submit_machine(self.machine, self.owner, True)
        administrator = User.objects.create_superuser(email="plate-review@example.invalid", is_test=True)
        review_submission(submission, administrator, "approved")
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.approved_version.data["public_asset_ids"], [])

    def test_whole_machine_observation_takes_precedence_over_plate_excerpt(self):
        job = self.job()
        job.result["image_observations"] = [{"asset_id": str(self.asset.pk), "kind": "machine"}]
        job.result["plates"] = [{"asset_id": str(self.asset.pk), "component": "machine", "readability": "clear"}]
        job.save(update_fields=["result"])
        self.assertEqual(detected_plate_asset_ids(self.machine), set())

    def test_foreign_asset_and_unselected_asset_cannot_be_classified_by_a_job(self):
        job = self.job()
        own_unselected = Asset.objects.create(machine=self.machine, kind="image", purpose="general",
            processing_status="ready", sha256="b" * 64, original="test/other.jpg", size=1, mime_type="image/jpeg")
        job.result["image_observations"] = [{"asset_id": str(own_unselected.pk), "kind": "plate"},
                                             {"asset_id": str(uuid.uuid4()), "kind": "plate"}]
        job.save(update_fields=["result"])
        self.assertEqual(detected_plate_asset_ids(self.machine), set())
