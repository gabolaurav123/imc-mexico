import json
from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from PIL import Image
from unittest.mock import patch

from portal.guest import purge_expired_guest_drafts
from portal.models import AnalysisJob, Asset, Category, Consent, GuestDraft, Machine, PlatformSettings, User


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    "default": {"BACKEND": "portal.storage.PrivateStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class GuestDraftTests(TestCase):
    def setUp(self):
        PlatformSettings.objects.create(pk=1)
        self.category = Category.objects.create(name="Excavadoras", slug="guest-excavators")
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.media = override_settings(MEDIA_ROOT=self.directory.name, PRIVATE_S3_BUCKET="")
        self.media.enable()
        self.addCleanup(self.media.disable)
        self.image_index = 0
        self.real_user = User.objects.create_user(email="owner@example.invalid", password="Guest-claim-password-123!", phone="+525512345678")

    def start(self, client=None, **values):
        client = client or self.client
        body = {"category": self.category.pk, "brand": "CAT", "model": "320", "description": "Excavadora con datos declarados.", **values}
        response = client.post("/api/invitados/", data=json.dumps(body), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def image(self):
        raw = BytesIO()
        self.image_index += 1
        Image.new("RGB", (48, 48), (self.image_index * 50, 0, 180)).save(raw, format="JPEG")
        return SimpleUploadedFile("machine.jpg", raw.getvalue(), content_type="image/jpeg")

    def test_guest_upload_rechecks_the_locked_three_photo_limit(self):
        payload = self.start()
        draft = GuestDraft.objects.get(pk=payload["id"])
        for _ in range(3):
            response = self.client.post(
                f"/api/invitados/{draft.pk}/archivos/", {"file": self.image(), "purpose": "general"}
            )
            self.assertEqual(response.status_code, 201, response.content)

        # The endpoint locks Machine and checks the count immediately before
        # ingesting, which is the check that also protects concurrent uploads.
        blocked = self.client.post(
            f"/api/invitados/{draft.pk}/archivos/", {"file": self.image(), "purpose": "general"}
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(Asset.objects.filter(machine=draft.machine).count(), 3)

    def test_guest_rejects_video_and_document_purpose_without_creating_assets(self):
        payload = self.start()
        draft = GuestDraft.objects.get(pk=payload["id"])
        video = SimpleUploadedFile("walkaround.mp4", b"not-a-video", content_type="video/mp4")
        rejected_video = self.client.post(
            f"/api/invitados/{draft.pk}/archivos/", {"file": video, "purpose": "general"}
        )
        self.assertEqual(rejected_video.status_code, 400)
        rejected_document = self.client.post(
            f"/api/invitados/{draft.pk}/archivos/", {"file": self.image(), "purpose": "document"}
        )
        self.assertEqual(rejected_document.status_code, 400)
        self.assertFalse(Asset.objects.filter(machine=draft.machine).exists())

    def test_guest_capability_is_session_bound_and_does_not_open_machine_api(self):
        payload = self.start()
        draft = GuestDraft.objects.get(pk=payload["id"])
        self.assertTrue(draft.owner.is_guest)
        self.assertTrue(draft.owner.is_test)
        self.assertFalse(draft.owner.has_usable_password())
        self.assertEqual(draft.machine.owner_id, draft.owner_id)
        self.assertEqual(draft.machine.data["currency"], "USD")
        self.assertEqual(self.client.get(f"/api/invitados/{draft.pk}/").status_code, 200)
        other = Client()
        self.assertEqual(other.get(f"/api/invitados/{draft.pk}/").status_code, 403)
        self.assertEqual(other.get(f"/api/maquinarias/{draft.machine_id}/").status_code, 401)
        wizard = self.client.get(f"/invitados/{draft.pk}/")
        self.assertEqual(wizard.status_code, 200)
        self.assertEqual(wizard.context["guest_api_base"], f"/api/invitados/{draft.pk}/")
        self.assertContains(wizard, 'data-max-images="3"')
        self.assertContains(wizard, 'id="guest-save-result"')
        self.assertNotContains(wizard, 'data-open-sheet')
        self.assertNotContains(wizard, 'id="download-draft-pdf"')
        self.client.force_login(draft.owner)
        self.assertEqual(self.client.get(f"/api/maquinarias/{draft.machine_id}/").status_code, 403)

    def test_claim_transfers_the_existing_machine_and_files_once(self):
        payload = self.start()
        draft = GuestDraft.objects.get(pk=payload["id"])
        upload = self.client.post(f"/api/invitados/{draft.pk}/archivos/", {"file": self.image(), "purpose": "plate"})
        self.assertEqual(upload.status_code, 201, upload.content)
        asset_id = upload.json()["id"]
        capability = self.client.session["guest_draft_capability"]
        self.client.force_login(self.real_user)
        response = self.client.get("/iniciar-sesion/")
        self.assertRedirects(response, f"/panel/maquinarias/{draft.machine_id}/")
        draft.refresh_from_db()
        machine = Machine.objects.get(pk=draft.machine_id)
        self.assertEqual(machine.owner_id, self.real_user.pk)
        self.assertEqual(draft.claimed_by_id, self.real_user.pk)
        self.assertEqual(Asset.objects.get(pk=asset_id).machine_id, machine.pk)
        self.assertEqual(self.client.get(f"/api/maquinarias/{machine.pk}/").status_code, 200)

        replay = Client()
        session = replay.session
        session["guest_draft_capability"] = capability
        session.save()
        replay.force_login(User.objects.create_user(email="other@example.invalid", password="Other-password-123!"))
        self.assertEqual(replay.get("/iniciar-sesion/").status_code, 302)
        machine.refresh_from_db()
        self.assertEqual(machine.owner_id, self.real_user.pk)

    def test_expired_draft_cannot_be_read_or_claimed(self):
        payload = self.start()
        draft = GuestDraft.objects.get(pk=payload["id"])
        draft.expires_at = timezone.now() - timedelta(seconds=1)
        draft.save(update_fields=["expires_at"])
        self.assertEqual(self.client.get(f"/api/invitados/{draft.pk}/").status_code, 410)
        self.client.force_login(self.real_user)
        self.client.get("/iniciar-sesion/")
        draft.refresh_from_db()
        self.assertIsNone(draft.claimed_by_id)
        self.assertEqual(Machine.objects.get(pk=draft.machine_id).owner_id, draft.owner_id)

    def test_guest_limits_reject_more_than_one_job_and_three_photos(self):
        payload = self.start()
        draft = GuestDraft.objects.get(pk=payload["id"])
        for _ in range(3):
            response = self.client.post(f"/api/invitados/{draft.pk}/archivos/", {"file": self.image(), "purpose": "general"})
            self.assertEqual(response.status_code, 201, response.content)
        fourth = self.client.post(f"/api/invitados/{draft.pk}/archivos/", {"file": self.image(), "purpose": "general"})
        self.assertEqual(fourth.status_code, 400)
        AnalysisJob.objects.create(machine=draft.machine, requested_by=draft.owner, revision=draft.machine.revision,
                                   fingerprint="a" * 64, asset_ids=[])
        body = {"consent": True, "revision": draft.machine.revision}
        limited = self.client.post(f"/api/invitados/{draft.pk}/analizar/", data=json.dumps(body), content_type="application/json")
        self.assertEqual(limited.status_code, 400)

    def test_guest_analysis_limit_rejects_retry_with_changed_revision_and_options(self):
        payload = self.start()
        draft = GuestDraft.objects.get(pk=payload["id"])
        existing = AnalysisJob.objects.create(
            machine=draft.machine, requested_by=draft.owner, revision=draft.machine.revision,
            fingerprint="e" * 64, asset_ids=[], mode="description",
        )
        # A differently shaped retry must not bypass the guest-wide one-job
        # budget before it reaches the normal enqueue/fingerprint logic.
        body = {
            "consent": True, "revision": draft.machine.revision + 1,
            "asset_ids": [], "mode": "analysis", "research": False, "auto_apply": True,
        }
        with patch("portal.processing.enqueue_analysis") as enqueue:
            response = self.client.post(
                f"/api/invitados/{draft.pk}/analizar/", data=json.dumps(body), content_type="application/json"
            )
        self.assertEqual(response.status_code, 400)
        enqueue.assert_not_called()
        self.assertEqual(AnalysisJob.objects.filter(machine=draft.machine).count(), 1)
        self.assertTrue(AnalysisJob.objects.filter(pk=existing.pk).exists())

    def test_anonymous_start_is_rate_limited(self):
        clients = [Client() for _ in range(4)]
        for client in clients[:3]:
            self.start(client)
        response = clients[3].post("/api/invitados/", data=json.dumps({}), content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_existing_guest_session_reuses_its_single_machine(self):
        first = self.start()
        second = self.client.post("/api/invitados/", data=json.dumps({"brand": "Otra", "model": "Máquina"}),
                                  content_type="application/json")
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()["id"], first["id"])
        self.assertEqual(GuestDraft.objects.count(), 1)
        self.assertEqual(Machine.objects.count(), 1)

    def test_new_authenticated_and_api_drafts_default_to_usd_without_changing_existing_records(self):
        existing = Machine.objects.create(owner=self.real_user, data={"currency": "MXN"})
        self.client.force_login(self.real_user)
        response = self.client.post("/panel/maquinarias/nueva/", {
            "category": self.category.pk, "brand": "CAT", "model": "320", "description": "Declaración manual",
        })
        created = Machine.objects.exclude(pk=existing.pk).get()
        self.assertRedirects(response, f"/panel/maquinarias/{created.pk}/")
        self.assertEqual(created.data, {"currency": "USD", "brand": "CAT", "model": "320", "description": "Declaración manual"})
        self.assertEqual(Machine.objects.get(pk=existing.pk).data["currency"], "MXN")
        api = self.client.post("/api/maquinarias/", data=json.dumps({"category": self.category.pk}), content_type="application/json")
        self.assertEqual(api.status_code, 201)
        self.assertEqual(Machine.objects.get(pk=api.json()["id"]).data["currency"], "USD")

    def test_guest_wizard_endpoints_keep_files_private_and_accept_manual_analysis_contract(self):
        payload = self.start()
        draft = GuestDraft.objects.get(pk=payload["id"])
        # The shared wizard has a guest API base and enforces the smaller
        # backend limit before uploads; this verifies the rendered integration
        # contract without relying on a browser-only branch.
        page = self.client.get(f"/invitados/{draft.pk}/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'data-api-base="/api/invitados/{draft.pk}/"')
        self.assertContains(page, 'data-max-images="3"')

        saved = self.client.post(f"/api/invitados/{draft.pk}/guardar/", data=json.dumps({
            "revision": draft.machine.revision, "title": "CAT 320 declarada", "category": self.category.pk,
            "data": {"brand": "CAT", "model": "320", "description": "Declaración manual"},
            "provenance": {"brand": {"source": "user", "review": "confirmed"},
                           "model": {"source": "user", "review": "confirmed"},
                           "description": {"source": "user", "review": "confirmed"}},
        }), content_type="application/json")
        self.assertEqual(saved.status_code, 200, saved.content)
        draft.machine.refresh_from_db()
        upload = self.client.post(f"/api/invitados/{draft.pk}/archivos/", {"file": self.image(), "purpose": "general"})
        self.assertEqual(upload.status_code, 201, upload.content)
        asset_id = upload.json()["id"]
        preview = self.client.get(f"/api/invitados/{draft.pk}/archivos/{asset_id}/")
        self.assertEqual(preview.status_code, 200)
        preview.close()
        self.assertEqual(Client().get(f"/api/invitados/{draft.pk}/archivos/{asset_id}/").status_code, 403)
        owner_client = Client()
        owner_client.force_login(self.real_user)
        self.assertEqual(owner_client.get(f"/archivos/{asset_id}/").status_code, 404)
        changed = self.client.post(f"/api/invitados/{draft.pk}/archivos/{asset_id}/accion/",
                                   data=json.dumps({"action": "cover"}), content_type="application/json")
        self.assertEqual(changed.status_code, 200, changed.content)

        captured = {}
        def enqueue(machine, user, asset_ids, mode, **kwargs):
            captured.update({"machine": machine.pk, "user": user.pk, "asset_ids": asset_ids,
                             "mode": mode, **kwargs})
            return AnalysisJob.objects.create(machine=machine, requested_by=user, revision=machine.revision,
                                              fingerprint="b" * 64, asset_ids=asset_ids or [], mode=mode,
                                              auto_apply=True)

        draft.machine.refresh_from_db()
        with patch("portal.processing.enqueue_analysis", side_effect=enqueue):
            analysis = self.client.post(f"/api/invitados/{draft.pk}/analizar/", data=json.dumps({
                "consent": True, "asset_ids": [asset_id], "revision": draft.machine.revision,
                "research": True, "mode": "analysis", "auto_apply": True,
            }), content_type="application/json")
        self.assertEqual(analysis.status_code, 200, analysis.content)
        self.assertEqual(captured["machine"], draft.machine_id)
        self.assertEqual(captured["user"], draft.owner_id)
        self.assertTrue(captured["auto_apply"])
        self.assertTrue(captured["research"])
        self.assertEqual(captured["mode"], "analysis")
        job_id = analysis.json()["id"]
        self.assertEqual(self.client.get(f"/api/invitados/{draft.pk}/analisis/{job_id}/").status_code, 200)

    def test_declared_serial_without_photos_uses_normal_description_analysis(self):
        payload = self.start(brand="Komatsu", model="PC210", serial="SN-123456", description="Excavadora declarada por su propietaria")
        draft = GuestDraft.objects.get(pk=payload["id"])
        captured = {}

        def enqueue(machine, user, asset_ids, mode, **kwargs):
            captured.update({"asset_ids": asset_ids, "mode": mode, **kwargs})
            return AnalysisJob.objects.create(machine=machine, requested_by=user, revision=machine.revision,
                                              fingerprint="d" * 64, asset_ids=[], mode=mode, auto_apply=True)

        with patch("portal.processing.enqueue_analysis", side_effect=enqueue):
            response = self.client.post(f"/api/invitados/{draft.pk}/analizar/", data=json.dumps({
                "consent": True, "asset_ids": [], "revision": draft.machine.revision,
                "research": True, "mode": "analysis", "auto_apply": True,
            }), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(captured["asset_ids"], [])
        self.assertEqual(captured["mode"], "description")
        self.assertTrue(captured["research"])
        self.assertTrue(captured["auto_apply"])

    def test_expiry_cleanup_preserves_claimed_work_and_defers_running_worker(self):
        expired = self.start()
        draft = GuestDraft.objects.get(pk=expired["id"])
        upload = self.client.post(f"/api/invitados/{draft.pk}/archivos/", {"file": self.image(), "purpose": "general"})
        asset = Asset.objects.get(pk=upload.json()["id"])
        file_name, storage = asset.original.name, asset.original.storage
        job = AnalysisJob.objects.create(machine=draft.machine, requested_by=draft.owner, revision=draft.machine.revision,
                                         fingerprint="c" * 64, asset_ids=[str(asset.pk)], status="running")
        Consent.objects.create(user=draft.owner, machine=draft.machine, kind="ai", granted=True)
        draft.expires_at = timezone.now() - timedelta(seconds=1)
        draft.save(update_fields=["expires_at"])

        deferred = purge_expired_guest_drafts()
        self.assertEqual(deferred, {"purged": 0, "deferred": 1, "skipped": 0})
        draft.machine.refresh_from_db()
        job.refresh_from_db()
        self.assertIsNotNone(Machine.all_objects.get(pk=draft.machine_id).deleted_at)
        self.assertTrue(job.result["draft_deleted"])
        self.assertTrue(Asset.objects.filter(pk=asset.pk).exists())

        job.status = "failed"
        job.save(update_fields=["status"])
        with self.captureOnCommitCallbacks(execute=True):
            purged = purge_expired_guest_drafts()
        self.assertEqual(purged, {"purged": 1, "deferred": 0, "skipped": 0})
        self.assertFalse(GuestDraft.objects.filter(pk=draft.pk).exists())
        self.assertFalse(Machine.all_objects.filter(pk=draft.machine_id).exists())
        self.assertFalse(Asset.objects.filter(pk=asset.pk).exists())
        self.assertFalse(AnalysisJob.objects.filter(pk=job.pk).exists())
        self.assertFalse(Consent.objects.filter(machine_id=draft.machine_id).exists())
        self.assertFalse(storage.exists(file_name))
        draft.owner.refresh_from_db()
        self.assertFalse(draft.owner.is_active)

        claimed = self.start()
        claimed_draft = GuestDraft.objects.get(pk=claimed["id"])
        claimed_draft.claimed_by = self.real_user
        claimed_draft.claimed_at = timezone.now()
        claimed_draft.machine.owner = self.real_user
        claimed_draft.machine.save(update_fields=["owner", "updated_at"])
        claimed_draft.expires_at = timezone.now() - timedelta(seconds=1)
        claimed_draft.save(update_fields=["claimed_by", "claimed_at", "expires_at"])
        self.assertEqual(purge_expired_guest_drafts(), {"purged": 0, "deferred": 0, "skipped": 0})
        self.assertTrue(GuestDraft.objects.filter(pk=claimed_draft.pk).exists())
        self.assertTrue(Machine.objects.filter(pk=claimed_draft.machine_id).exists())

    def test_cleanup_command_runs_the_same_lifecycle(self):
        payload = self.start()
        draft = GuestDraft.objects.get(pk=payload["id"])
        draft.expires_at = timezone.now() - timedelta(seconds=1)
        draft.save(update_fields=["expires_at"])
        call_command("purge_guest_drafts", "--limit", "1")
        self.assertFalse(GuestDraft.objects.filter(pk=draft.pk).exists())
