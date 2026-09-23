"""The private machine API is a read model, never a background-work trigger."""
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from PIL import Image

from portal.models import AnalysisJob, Asset, AuditEvent, Category, Machine, User


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False,
                   STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
                             "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class MachineApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="api-owner@example.invalid", password="Owner-password-long123")
        cls.other = User.objects.create_user(email="api-other@example.invalid", password="Other-password-long123")
        cls.operator = User.objects.create_user(email="api-operator@example.invalid", password="Operator-password-long123", is_staff=True)
        cls.operator.user_permissions.add(*Permission.objects.filter(content_type__app_label="portal", codename__in=["operate_platform", "view_machine"]))
        cls.staff_without_view = User.objects.create_user(email="api-staff-without-view@example.invalid", password="Staff-password-long123", is_staff=True)
        cls.staff_without_view.user_permissions.add(Permission.objects.get(content_type__app_label="portal", codename="operate_platform"))
        cls.category = Category.objects.create(name="Excavadoras", slug="excavadoras", fields=[{"key": "boom_configuration"}])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        media = override_settings(MEDIA_ROOT=self.directory.name, PRIVATE_S3_BUCKET="")
        media.enable()
        self.addCleanup(media.disable)
        self.machine = Machine.objects.create(owner=self.owner, category=self.category, title="Excavadora privada",
                                              data={"serial": "SERIE-PRIVADA", "hours": 0},
                                              provenance={"serial": {"source": "user", "review": "confirmed"}})
        raw = BytesIO()
        Image.new("RGB", (24, 24), "navy").save(raw, format="JPEG")
        self.asset = Asset(machine=self.machine, kind="image", purpose="plate", processing_status="ready",
                           mime_type="image/jpeg", sha256="a" * 64, size=len(raw.getvalue()))
        self.asset.original.save("secret-upload.jpg", ContentFile(raw.getvalue()), save=False)
        self.asset.save()
        self.url = f"/api/maquinarias/{self.machine.pk}/"

    def verified_login(self, user):
        self.client.force_login(user)
        device = TOTPDevice.objects.create(user=user, name="API", confirmed=True)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def test_owner_gets_current_private_document_without_storage_keys_or_work(self):
        AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, revision=self.machine.revision, fingerprint="b" * 64)
        self.client.force_login(self.owner)
        before = {"revision": self.machine.revision, "jobs": AnalysisJob.objects.count(), "audit": AuditEvent.objects.count()}
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Vary"], "Cookie")
        body = response.json()
        self.assertEqual(body["schema_version"], "private-machine-v1")
        self.assertEqual(body["folio"], self.machine.folio)
        self.assertEqual(body["title"], "Excavadora privada")
        self.assertEqual(body["revision"], before["revision"])
        self.assertTrue(body["created_at"])
        self.assertTrue(body["updated_at"])
        self.assertEqual(body["category"], {"id": self.category.pk, "name": "Excavadoras", "slug": "excavadoras"})
        self.assertNotIn("fields", body["category"])
        self.assertEqual(body["data"]["serial"], "SERIE-PRIVADA")
        self.assertEqual(body["assets"][0]["url"], f"/archivos/{self.asset.pk}/")
        self.assertNotIn("secret-upload.jpg", response.content.decode())
        self.assertNotIn("machines/", response.content.decode())
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.revision, before["revision"])
        self.assertEqual(AnalysisJob.objects.count(), before["jobs"])
        self.assertEqual(AuditEvent.objects.count(), before["audit"])

    def test_authentication_and_object_scope_do_not_redirect_or_enumerate(self):
        anonymous = self.client.get(self.url)
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(anonymous.json()["error"], "Inicia sesión para continuar.")
        self.assertEqual(anonymous["Cache-Control"], "private, no-store")
        self.assertEqual(anonymous["Vary"], "Cookie")
        self.client.force_login(self.other)
        denied = self.client.get(self.url)
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(denied.json()["error"], "El registro no está disponible.")
        self.assertEqual(denied["Cache-Control"], "private, no-store")
        self.assertEqual(denied["Vary"], "Cookie")
        self.machine.deleted_at = self.machine.created_at
        self.machine.save(update_fields=["deleted_at"])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_inactive_owner_and_unverified_staff_cannot_read_while_verified_operator_can(self):
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.owner.is_active = True
        self.owner.save(update_fields=["is_active"])
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.verified_login(self.operator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.machine.pk))
        self.verified_login(self.staff_without_view)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_non_get_is_not_a_read_or_mutation_path(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {}, content_type="application/json")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "GET")
        self.assertEqual(response.json()["error"], "Método no permitido.")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Vary"], "Cookie")
