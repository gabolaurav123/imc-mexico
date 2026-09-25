"""Preparing again may renew AI prose only while the exact old prose is untouched."""
from copy import deepcopy
import uuid

from django.test import TestCase

from portal.models import AnalysisJob, Asset, Consent, Machine, User
from portal.research import compose_description, empty_research
from portal.services import apply_analysis_automatically, automatic_application_snapshot, save_draft


OLD = "Maquinaria. Cabina cerrada."


class AutomaticDescriptionRefreshTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="refresh-description@example.invalid", is_test=True)
        self.machine = Machine.objects.create(owner=self.owner, title="Título conservado", data={"description": OLD})
        self.asset = Asset.objects.create(machine=self.machine, kind="image", purpose="general", processing_status="ready",
                                         sha256="a" * 64, size=1, mime_type="image/jpeg", original="test/general.jpg")
        previous = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, revision=self.machine.revision,
                                              fingerprint=uuid.uuid4().hex, status="completed")
        self.original_meta = {"source": "system", "review": "needs_review", "analysis_id": str(previous.pk)}
        self.machine.provenance = {"description": deepcopy(self.original_meta)}
        self.machine.save()
        Consent.objects.create(user=self.owner, machine=self.machine, kind="ai", granted=True)

    def job(self, visual="Ruedas visibles y hoja niveladora central."):
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, revision=self.machine.revision,
            fingerprint=uuid.uuid4().hex, status="completed", asset_ids=[str(self.asset.pk)], auto_apply=True,
            application_snapshot=automatic_application_snapshot(self.machine),
            result={"data": {}, "provenance": {}, "fields": [], "plates": [], "visual_description": visual,
                    "research": empty_research("insufficient_identifiers")})

    def apply(self, job):
        self.machine, summary = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        return summary

    def test_unchanged_automatic_description_refreshes_once_with_new_provenance(self):
        job = self.job()
        self.assertEqual(job.application_snapshot["refresh_description"], {"value": OLD, "provenance": self.original_meta})
        self.assertIn("description", job.application_snapshot["eligible_fields"])
        summary = self.apply(job)
        self.assertEqual(summary["applied_fields"], ["description"])
        self.assertEqual(self.machine.data["description"], compose_description({}, {}, None))
        self.assertNotIn("Cabina cerrada", self.machine.data["description"])
        self.assertEqual(self.machine.provenance["description"]["analysis_id"], str(job.pk))
        self.assertEqual(self.machine.title, "Título conservado")
        self.assertEqual(set(self.machine.data), {"description"})
        revision = self.machine.revision
        self.assertEqual(self.apply(job), summary)
        self.assertEqual(self.machine.revision, revision)
        self.machine = save_draft(self.machine, self.owner, {"data": {"description": "Edición humana posterior."}}, self.machine.revision)
        self.apply(job)
        self.assertEqual(self.machine.data["description"], "Edición humana posterior.")

    def test_human_text_confirmation_and_clear_before_or_during_request_are_protected(self):
        for during in (False, True):
            for value, confirmed in (("Descripción humana.", False), ("", False), (OLD, True)):
                with self.subTest(during=during, value=value, confirmed=confirmed):
                    self.machine.data = {"description": OLD}
                    self.machine.provenance = {"description": deepcopy(self.original_meta)}
                    self.machine.save()
                    job = self.job() if during else None
                    payload = {"data": {"description": value}}
                    if confirmed:
                        payload["provenance"] = {"description": {"source": "user", "review": "confirmed"}}
                    self.machine = save_draft(self.machine, self.owner, payload, self.machine.revision)
                    if not during:
                        job = self.job()
                        self.assertNotIn("refresh_description", job.application_snapshot)
                    summary = self.apply(job)
                    self.assertNotIn("description", summary["applied_fields"])
                    self.assertEqual(self.machine.data["description"], value)
                    self.assertEqual(self.machine.provenance["description"]["review"], "confirmed")

    def test_intermediate_job_provenance_blocks_older_refresh_even_when_text_is_identical(self):
        older = self.job("Texto visible de un trabajo anterior.")
        newer = self.job("Cabina cerrada.")
        self.apply(newer)
        self.assertEqual(self.machine.data["description"], compose_description({}, {}, None))
        self.assertEqual(self.machine.provenance["description"]["analysis_id"], str(newer.pk))
        summary = self.apply(older)
        self.assertNotIn("description", summary["applied_fields"])
        self.assertEqual(self.machine.data["description"], compose_description({}, {}, None))
        self.assertEqual(self.machine.provenance["description"]["analysis_id"], str(newer.pk))

    def test_legacy_job_without_durable_refresh_record_never_replaces_existing_ai_text(self):
        job = self.job()
        job.application_snapshot = {}
        job.save(update_fields=["application_snapshot"])
        summary = self.apply(job)
        self.assertNotIn("description", summary["applied_fields"])
        self.assertEqual(self.machine.data["description"], OLD)
        self.assertEqual(self.machine.provenance["description"], self.original_meta)
