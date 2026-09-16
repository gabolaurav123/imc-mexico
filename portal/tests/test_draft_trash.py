"""Draft removal is private, revision checked and recoverable."""
from copy import deepcopy
from io import BytesIO
import json
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from PIL import Image

from portal.models import AnalysisJob, Asset, AuditEvent, Machine, MachineVersion, Publication, Submission, User


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False, PRIVATE_S3_BUCKET="",
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class DraftTrashTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="imc-draft-trash-")
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=directory.name)
        media.enable()
        self.addCleanup(media.disable)
        self.owner = User.objects.create_user(email="trash-owner@example.invalid", is_test=True)
        self.other = User.objects.create_user(email="trash-other@example.invalid", is_test=True)
        self.machine = Machine.objects.create(owner=self.owner, title="Borrador exclusivo de prueba",
            data={"brand": "CAT", "serial": "PRIVATE-SERIAL", "description": "Descripción conservada"},
            provenance={"brand": {"source": "user", "review": "confirmed"}})
        raw = BytesIO()
        Image.new("RGB", (80, 60), "yellow").save(raw, format="JPEG")
        self.photo = Asset(machine=self.machine, kind="image", purpose="general", processing_status="ready",
                           mime_type="image/jpeg", sha256="a" * 64, size=len(raw.getvalue()))
        self.photo.original.save("trash.jpg", ContentFile(raw.getvalue()), save=False)
        self.photo.preview.save("trash-preview.jpg", ContentFile(raw.getvalue()), save=False)
        self.photo.save()
        self.client.force_login(self.owner)

    def action(self, action="delete_draft", revision=1, machine=None, client=None):
        target = machine or self.machine
        return (client or self.client).post(f"/api/maquinarias/{target.pk}/accion/",
            json.dumps({"action": action, "revision": revision}), content_type="application/json")

    def test_delete_hides_from_active_list_dashboard_and_preserves_private_files(self):
        data, provenance = deepcopy(self.machine.data), deepcopy(self.machine.provenance)
        response = self.action()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(Machine.objects.filter(pk=self.machine.pk).exists())
        stored = Machine.all_objects.get(pk=self.machine.pk)
        self.assertIsNotNone(stored.deleted_at)
        self.assertFalse(stored.editable)
        self.assertFalse(stored.can_delete_draft)
        self.assertEqual(stored.revision, 2)
        self.assertEqual(stored.data, data)
        self.assertEqual(stored.provenance, provenance)
        self.assertTrue(Asset.objects.filter(pk=self.photo.pk).exists())
        self.assertTrue(self.photo.original.storage.exists(self.photo.original.name))
        self.assertTrue(self.photo.preview.storage.exists(self.photo.preview.name))
        self.assertNotContains(self.client.get("/panel/maquinarias/"), self.machine.title)
        panel = self.client.get("/panel/")
        self.assertEqual(panel.context["counts"]["drafts"], 0)
        self.assertEqual(panel.context["counts"]["total"], 0)
        self.assertNotContains(panel, self.machine.title)
        trash = self.client.get("/panel/maquinarias/?papelera=1")
        self.assertContains(trash, self.machine.title)
        self.assertContains(trash, "Restaurar")

    def test_restore_recovers_same_data_files_and_can_be_edited_again(self):
        self.assertEqual(self.action().status_code, 200)
        self.assertEqual(self.action("restore_draft", 2).status_code, 200)
        restored = Machine.objects.get(pk=self.machine.pk)
        self.assertIsNone(restored.deleted_at)
        self.assertEqual(restored.revision, 3)
        self.assertEqual(restored.data, self.machine.data)
        self.assertEqual(restored.assets.get().pk, self.photo.pk)
        self.assertTrue(restored.can_delete_draft)
        self.assertContains(self.client.get("/panel/maquinarias/"), self.machine.title)
        self.assertNotContains(self.client.get("/panel/maquinarias/?papelera=1"), self.machine.title)
        response = self.client.post(f"/api/maquinarias/{self.machine.pk}/guardar/",
            json.dumps({"revision": 3, "title": "Borrador restaurado y corregido"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)

    def test_delete_and_restore_are_audited_without_removing_version_history(self):
        version = MachineVersion.objects.create(machine=self.machine, number=1,
            data={"title": "Instantánea histórica", "asset_ids": [str(self.photo.pk)]}, created_by=self.owner)
        self.assertEqual(self.action().status_code, 200)
        self.assertEqual(self.action("restore_draft", 2).status_code, 200)
        self.assertTrue(MachineVersion.objects.filter(pk=version.pk).exists())
        for action in ("machine.draft_deleted", "machine.draft_restored"):
            with self.subTest(action=action):
                self.assertTrue(AuditEvent.objects.filter(actor=self.owner, action=action).exists())

    def test_deleted_machine_never_serves_public_content_even_with_an_old_share_record(self):
        self.owner.advertiser_status = "approved"
        self.owner.save(update_fields=["advertiser_status"])
        version = MachineVersion.objects.create(machine=self.machine, number=1,
            data={"title": "Ficha anterior", "asset_ids": [str(self.photo.pk)],
                  "public_asset_ids": [str(self.photo.pk)]}, created_by=self.owner)
        self.machine.approved_version = version
        self.machine.deleted_at = timezone.now()
        self.machine.save(update_fields=["approved_version", "deleted_at"])
        self.photo.public_authorized = True
        self.photo.save(update_fields=["public_authorized"])
        pub = Publication.objects.create(machine=self.machine, version=version, enabled=True, status="published")
        self.client.logout()
        for suffix in ("", "pdf/", f"archivo/{self.photo.pk}/"):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.client.get(f"/ficha/{pub.token}/" + suffix).status_code, 404)

    def test_admin_review_action_keeps_deleted_draft_history_unchanged(self):
        version = MachineVersion.objects.create(machine=self.machine, number=1, data={}, created_by=self.owner)
        submission = Submission.objects.create(machine=self.machine, version=version, status="rejected")
        self.assertEqual(self.action().status_code, 200)
        admin = User.objects.create_superuser(email="trash-review@example.invalid", password="qa-only-test-password")
        device = TOTPDevice.objects.create(user=admin, name="QA", confirmed=True)
        self.client.force_login(admin)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        response = self.client.post("/admin/portal/submission/", {"action": "cancel",
            "_selected_action": str(submission.pk), "reason": "Prueba de historial protegido"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Se omitieron las solicitudes")
        submission.refresh_from_db()
        self.assertEqual(submission.status, "rejected")
        self.assertIsNotNone(Machine.all_objects.get(pk=self.machine.pk).deleted_at)

    def test_old_revision_neither_removes_nor_restores_a_changed_draft(self):
        Machine.objects.filter(pk=self.machine.pk).update(revision=4, title="Cambio de otra pestaña")
        self.assertEqual(self.action(revision=1).status_code, 409)
        self.assertTrue(Machine.objects.filter(pk=self.machine.pk).exists())
        self.assertEqual(self.action(revision=4).status_code, 200)
        self.assertEqual(self.action("restore_draft", 4).status_code, 409)
        self.assertFalse(Machine.objects.filter(pk=self.machine.pk).exists())
        self.assertEqual(self.action("restore_draft", 5).status_code, 200)
        self.assertEqual(Machine.objects.get(pk=self.machine.pk).title, "Cambio de otra pestaña")

    def test_missing_or_invalid_revision_does_not_delete(self):
        endpoint = f"/api/maquinarias/{self.machine.pk}/accion/"
        for revision in (None, "bad", -1, 0, True, 1.5):
            with self.subTest(revision=revision):
                response = self.action(revision=revision)
                self.assertIn(response.status_code, (400, 409))
                self.assertTrue(Machine.objects.filter(pk=self.machine.pk).exists())
        response = self.client.post(endpoint, json.dumps({"action": "delete_draft"}), content_type="application/json")
        self.assertIn(response.status_code, (400, 409))

    def test_only_owner_can_delete_or_restore_even_with_verified_staff_access(self):
        admin = User.objects.create_superuser(email="trash-admin@example.invalid", password="qa-only-test-password")
        device = TOTPDevice.objects.create(user=admin, name="QA", confirmed=True)
        self.client.force_login(self.other)
        self.assertEqual(self.action().status_code, 404)
        self.client.force_login(admin)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        self.assertIn(self.action().status_code, (403, 404))
        self.client.force_login(self.owner)
        self.assertEqual(self.action().status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.action("restore_draft", 2).status_code, 404)
        self.assertNotContains(self.client.get("/panel/maquinarias/?papelera=1"), self.machine.title)
        self.client.force_login(admin)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        self.assertIn(self.action("restore_draft", 2).status_code, (403, 404))
        self.assertIsNotNone(Machine.all_objects.get(pk=self.machine.pk).deleted_at)

    def test_mutation_requires_post_login_and_csrf(self):
        endpoint = f"/api/maquinarias/{self.machine.pk}/accion/"
        self.assertEqual(self.client.get(endpoint, {"action": "delete_draft", "revision": 1}).status_code, 405)
        self.client.logout()
        self.assertEqual(self.action().status_code, 401)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.owner)
        self.assertEqual(self.action(client=protected).status_code, 403)
        self.assertTrue(Machine.objects.filter(pk=self.machine.pk).exists())

    def test_all_non_draft_statuses_are_rejected(self):
        for status in Machine.Status.values:
            if status == "draft":
                continue
            with self.subTest(status=status):
                target = Machine.objects.create(owner=self.owner, status=status)
                self.assertFalse(target.can_delete_draft)
                self.assertEqual(self.action(machine=target).status_code, 400)
                self.assertTrue(Machine.objects.filter(pk=target.pk).exists())

    def test_draft_of_previously_approved_equipment_cannot_be_deleted(self):
        version = MachineVersion.objects.create(machine=self.machine, number=1, data={}, created_by=self.owner)
        self.machine.approved_version = version
        self.machine.save(update_fields=["approved_version"])
        self.assertFalse(self.machine.can_delete_draft)
        self.assertEqual(self.action().status_code, 400)
        self.assertTrue(Machine.objects.filter(pk=self.machine.pk).exists())

    def test_active_publication_blocks_deletion_even_if_approved_pointer_is_missing(self):
        version = MachineVersion.objects.create(machine=self.machine, number=1, data={}, created_by=self.owner)
        Publication.objects.create(machine=self.machine, version=version, destination="share", enabled=True, status="published")
        self.assertEqual(self.action().status_code, 400)
        self.assertTrue(Machine.objects.filter(pk=self.machine.pk).exists())

    def test_deleted_draft_is_inaccessible_to_files_pdf_edits_analysis_and_submission(self):
        job = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, revision=1,
                                        fingerprint="b" * 64, status="completed")
        self.assertEqual(self.action().status_code, 200)
        for path in (f"/panel/maquinarias/{self.machine.pk}/", f"/panel/maquinarias/{self.machine.pk}/ficha/",
                     f"/panel/maquinarias/{self.machine.pk}/pdf/", f"/archivos/{self.photo.pk}/",
                     f"/api/analisis/{job.pk}/", f"/contacto/?maquinaria={self.machine.pk}"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        actions = {"guardar": {"revision": 2, "title": "No resucitar"}, "analizar": {"consent": True},
                   "enviar": {"advertise_consent": True}, "aplicar": {}, "archivos": {}}
        with patch("portal.processing.enqueue_analysis") as enqueue:
            for endpoint, body in actions.items():
                with self.subTest(endpoint=endpoint):
                    response = self.client.post(f"/api/maquinarias/{self.machine.pk}/{endpoint}/",
                                               json.dumps(body), content_type="application/json")
                    self.assertEqual(response.status_code, 404)
            enqueue.assert_not_called()
        self.assertIsNotNone(Machine.all_objects.get(pk=self.machine.pk).deleted_at)

    def test_rendered_delete_controls_are_limited_to_eligible_drafts(self):
        draft = self.client.get(f"/panel/maquinarias/{self.machine.pk}/")
        self.assertContains(draft, "Eliminar borrador")
        self.assertContains(self.client.get("/panel/maquinarias/"), "Eliminar borrador")
        self.machine.status = "submitted"
        self.machine.save(update_fields=["status"])
        self.assertNotContains(self.client.get(f"/panel/maquinarias/{self.machine.pk}/"), "Eliminar borrador")
        self.assertNotContains(self.client.get("/panel/maquinarias/"), "Eliminar borrador")
