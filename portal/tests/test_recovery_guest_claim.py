import json
from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.tokens import default_token_generator
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from PIL import Image

from portal.models import Asset, Category, GuestDraft, Machine, PlatformSettings, User


@override_settings(SECURE_SSL_REDIRECT=False, STAFF_MFA_REQUIRED=True, STORAGES={
    "default": {"BACKEND": "portal.storage.PrivateStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class RecoveryGuestClaimTests(TestCase):
    password = "Recovered-access-5917!"

    def setUp(self):
        PlatformSettings.objects.create(pk=1)
        self.category = Category.objects.create(name="Excavadoras", slug="recovery-excavators")
        self.user = User.objects.create_user(
            email="recovery-owner@example.invalid", password="Existing-access-9358!",
        )
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        media = override_settings(MEDIA_ROOT=self.directory.name, PRIVATE_S3_BUCKET="")
        media.enable()
        self.addCleanup(media.disable)

    def start_draft(self):
        response = self.client.post("/api/invitados/", data=json.dumps({
            "category": self.category.pk, "brand": "CAT", "model": "320",
            "description": "Excavadora con datos declarados.",
        }), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        return GuestDraft.objects.get(pk=response.json()["id"])

    def reset_path(self, user=None, token=None):
        user = user or self.user
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = token or default_token_generator.make_token(user)
        return f"/activar/{uid}/{token}/"

    def reset(self, path):
        return self.client.post(path, {
            "new_password1": self.password, "new_password2": self.password,
        })

    def test_reset_claims_existing_draft_and_preserves_uploaded_photo(self):
        draft = self.start_draft()
        original_data = draft.machine.data.copy()
        raw = BytesIO()
        Image.new("RGB", (48, 48), (100, 0, 180)).save(raw, format="JPEG")
        uploaded = self.client.post(f"/api/invitados/{draft.pk}/archivos/", {
            "file": SimpleUploadedFile("machine.jpg", raw.getvalue(), content_type="image/jpeg"),
            "purpose": "plate",
        })
        self.assertEqual(uploaded.status_code, 201, uploaded.content)
        asset = Asset.objects.get(pk=uploaded.json()["id"])
        original_file = asset.original.name

        response = self.reset(self.reset_path())

        self.assertRedirects(response, f"/panel/maquinarias/{draft.machine_id}/")
        draft.refresh_from_db()
        draft.machine.refresh_from_db()
        asset.refresh_from_db()
        self.assertEqual(draft.claimed_by_id, self.user.pk)
        self.assertEqual(draft.machine.owner_id, self.user.pk)
        self.assertEqual(draft.machine.data, original_data)
        self.assertEqual(Machine.objects.count(), 1)
        self.assertEqual(asset.machine_id, draft.machine_id)
        self.assertEqual(asset.original.name, original_file)
        self.assertTrue(asset.original.storage.exists(asset.original.name))
        self.assertNotIn("guest_draft_capability", self.client.session)
        self.assertEqual(self.client.get(f"/api/maquinarias/{draft.machine_id}/").status_code, 200)

    def test_reset_without_guest_draft_keeps_normal_destination(self):
        response = self.reset(self.reset_path())
        self.assertRedirects(response, "/panel/", fetch_redirect_response=False)
        self.assertFalse(GuestDraft.objects.exists())
        self.assertFalse(Machine.objects.exists())

    def test_invalid_reset_token_neither_logs_in_nor_claims_draft(self):
        draft = self.start_draft()
        capability = self.client.session["guest_draft_capability"]
        response = self.reset(self.reset_path(token="invalid-token"))
        self.assertContains(response, "Este enlace venció o ya se utilizó")
        self.assertTrue(response.context["recovery_required"])
        draft.refresh_from_db()
        draft.machine.refresh_from_db()
        self.assertIsNone(draft.claimed_by_id)
        self.assertEqual(draft.machine.owner_id, draft.owner_id)
        self.assertEqual(self.client.session["guest_draft_capability"], capability)
        self.assertNotIn("_auth_user_id", self.client.session)

    @patch("portal.auth_views.throttle", return_value=False)
    def test_exhausted_reset_attempts_show_an_error_and_keep_draft_and_token(self, throttle):
        draft = self.start_draft()
        token = default_token_generator.make_token(self.user)
        response = self.reset(self.reset_path(token=token))
        self.assertContains(response, "Se alcanzó el límite de intentos")
        self.assertContains(response, "dentro de una hora")
        self.assertIn("__all__", response.context["form"].errors)
        throttle.assert_called_once()
        self.user.refresh_from_db()
        draft.refresh_from_db()
        self.assertTrue(default_token_generator.check_token(self.user, token))
        self.assertIsNone(draft.claimed_by_id)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_invalid_guest_capability_does_not_transfer_another_draft(self):
        draft = self.start_draft()
        session = self.client.session
        capability = dict(session["guest_draft_capability"])
        capability["secret"] = "invalid-secret"
        session["guest_draft_capability"] = capability
        session.save()

        response = self.reset(self.reset_path())

        self.assertRedirects(response, "/panel/", fetch_redirect_response=False)
        draft.refresh_from_db()
        draft.machine.refresh_from_db()
        self.assertIsNone(draft.claimed_by_id)
        self.assertEqual(draft.machine.owner_id, draft.owner_id)
        self.assertNotIn("guest_draft_capability", self.client.session)

    def test_expired_guest_draft_remains_unclaimed_after_reset(self):
        draft = self.start_draft()
        draft.expires_at = timezone.now() - timedelta(seconds=1)
        draft.save(update_fields=["expires_at"])
        response = self.reset(self.reset_path())
        self.assertRedirects(response, "/panel/", fetch_redirect_response=False)
        draft.refresh_from_db()
        self.assertIsNone(draft.claimed_by_id)

    def test_staff_reset_preserves_draft_without_bypassing_security_route(self):
        draft = self.start_draft()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        response = self.reset(self.reset_path())
        self.assertRedirects(response, "/panel/seguridad/", fetch_redirect_response=False)
        draft.refresh_from_db()
        self.assertEqual(draft.claimed_by_id, self.user.pk)
        self.assertEqual(draft.machine.owner_id, self.user.pk)
        protected = self.client.get("/admin/")
        self.assertEqual(protected.status_code, 302)
        self.assertTrue(protected.url.startswith("/panel/seguridad/"))
