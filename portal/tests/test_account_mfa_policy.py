"""Per-account management MFA exemptions keep authorization boundaries intact."""

from io import StringIO

from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from portal.models import AuditEvent, User
from portal.security import needs_management_mfa, staff_authorized


@override_settings(
    STAFF_MFA_REQUIRED=True,
    SECURE_SSL_REDIRECT=False,
    DEBUG=False,
    ALLOWED_HOSTS=["testserver"],
    STORAGES={
        "default": {"BACKEND": "portal.storage.PrivateStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class AccountMfaPolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "Local-account-mfa-policy-974!"
        cls.admin = User.objects.create_superuser(
            email="gabolaurav@gmail.com", password=cls.password
        )
        cls.other_staff = User.objects.create_user(
            email="other-staff@example.invalid", password=cls.password, is_staff=True
        )
        cls.other_staff.user_permissions.add(
            Permission.objects.get(content_type__app_label="portal", codename="operate_platform")
        )
        cls.limited_staff = User.objects.create_user(
            email="limited-staff@example.invalid", password=cls.password, is_staff=True
        )
        cls.limited_staff.user_permissions.add(
            Permission.objects.get(content_type__app_label="portal", codename="view_lead")
        )
        cls.owner = User.objects.create_user(
            email="regular-owner@example.invalid", password=cls.password
        )

    def enable_admin_exemption(self):
        User.objects.filter(pk=self.admin.pk).update(management_mfa_required=False)
        self.admin.refresh_from_db()

    def force_login(self, user):
        self.client.force_login(user)

    def verified_login(self, user):
        self.force_login(user)
        device = TOTPDevice.objects.create(user=user, name="test-device", confirmed=True)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        return device

    def test_exempt_admin_enters_operations_and_django_admin_without_otp(self):
        self.enable_admin_exemption()
        self.force_login(self.admin)

        self.assertFalse(needs_management_mfa(self.admin))
        self.assertTrue(staff_authorized(self.admin))
        self.assertEqual(self.client.get("/operaciones/").status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        self.assertFalse(TOTPDevice.objects.filter(user=self.admin).exists())
        self.assertNotIn(DEVICE_ID_SESSION_KEY, self.client.session)

    def test_exemption_does_not_change_admin_permissions_or_enable_other_staff(self):
        self.enable_admin_exemption()
        self.assertTrue(self.admin.is_staff)
        self.assertTrue(self.admin.is_superuser)
        self.assertTrue(self.admin.has_perm("portal.operate_platform"))

        self.force_login(self.other_staff)
        self.assertTrue(needs_management_mfa(self.other_staff))
        response = self.client.get("/operaciones/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/panel/seguridad/"))
        self.assertFalse(TOTPDevice.objects.filter(user=self.other_staff).exists())

    def test_limited_staff_and_nonstaff_remain_blocked_with_exempt_admin(self):
        self.enable_admin_exemption()

        self.verified_login(self.limited_staff)
        self.assertEqual(self.client.get("/operaciones/").status_code, 403)
        self.assertFalse(self.limited_staff.has_perm("portal.operate_platform"))
        self.assertEqual(self.client.get("/admin/portal/user/").status_code, 403)

        self.force_login(self.owner)
        self.assertEqual(self.client.get("/operaciones/").status_code, 403)
        self.assertFalse(self.owner.is_staff)
        self.assertFalse(TOTPDevice.objects.filter(user=self.owner).exists())

    def test_reenabling_admin_flag_restores_mfa_gate(self):
        self.enable_admin_exemption()
        self.assertFalse(needs_management_mfa(self.admin))
        User.objects.filter(pk=self.admin.pk).update(management_mfa_required=True)
        self.admin.refresh_from_db()
        self.assertTrue(needs_management_mfa(self.admin))

        self.force_login(self.admin)
        response = self.client.get("/operaciones/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/panel/seguridad/"))

    def test_disabled_admin_security_page_has_no_qr_and_creates_no_device(self):
        existing_device = TOTPDevice.objects.create(
            user=self.admin, name="IMC", confirmed=False
        )
        self.enable_admin_exemption()
        self.force_login(self.admin)

        response = self.client.get("/panel/seguridad/?next=/operaciones/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["needs_management_mfa"])
        self.assertIsNone(response.context["device"])
        self.assertIsNone(response.context["qr"])
        self.assertNotContains(response, "name=\"token\"")
        self.assertNotContains(response, "data:image/png;base64,")
        self.assertTrue(TOTPDevice.objects.filter(pk=existing_device.pk).exists())

    def test_exempt_admin_keeps_operator_and_communications_access(self):
        self.enable_admin_exemption()
        self.force_login(self.admin)

        self.assertTrue(staff_authorized(self.admin))
        response = self.client.get("/operaciones/notificaciones/nueva/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Destinatario")

    def test_set_admin_mfa_command_toggles_only_existing_active_staff_and_audits(self):
        existing_device = TOTPDevice.objects.create(
            user=self.admin, name="IMC", confirmed=True
        )
        password_hash = self.admin.password
        role_snapshot = (self.admin.is_active, self.admin.is_staff, self.admin.is_superuser)
        permission_snapshot = set(self.admin.user_permissions.values_list("pk", flat=True))

        output = StringIO()
        call_command(
            "set_admin_mfa", self.admin.email, "--disable", "--reason", "Temporary support exception",
            stdout=output,
        )
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.management_mfa_required)
        self.assertEqual(self.admin.password, password_hash)
        self.assertEqual((self.admin.is_active, self.admin.is_staff, self.admin.is_superuser), role_snapshot)
        self.assertEqual(set(self.admin.user_permissions.values_list("pk", flat=True)), permission_snapshot)
        self.assertTrue(TOTPDevice.objects.filter(pk=existing_device.pk).exists())
        event = AuditEvent.objects.get(action="security.admin_mfa_policy_changed")
        self.assertEqual(event.actor, None)
        self.assertEqual(event.object_id, str(self.admin.pk))
        self.assertEqual(event.metadata["reason"], "Temporary support exception")
        self.assertFalse(event.metadata["required"])

        output = StringIO()
        call_command(
            "set_admin_mfa", self.admin.email, "--disable", "--reason", "Repeat request",
            stdout=output,
        )
        self.assertEqual(AuditEvent.objects.filter(action="security.admin_mfa_policy_changed").count(), 1)
        self.assertIn("ya tiene", output.getvalue())

        call_command(
            "set_admin_mfa", self.admin.email, "--enable", "--reason", "Exception ended",
            stdout=StringIO(),
        )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.management_mfa_required)
        self.assertEqual(AuditEvent.objects.filter(action="security.admin_mfa_policy_changed").count(), 2)
        self.assertEqual(self.admin.password, password_hash)
        self.assertTrue(TOTPDevice.objects.filter(pk=existing_device.pk).exists())

    def test_set_admin_mfa_command_rejects_missing_nonstaff_and_inactive_accounts(self):
        inactive_staff = User.objects.create_user(
            email="inactive-staff@example.invalid", password=self.password, is_staff=True, is_active=False
        )
        cases = {
            "missing@example.invalid": None,
            self.owner.email: self.owner,
            inactive_staff.email: inactive_staff,
        }
        for email, user in cases.items():
            with self.subTest(email=email):
                with self.assertRaises(CommandError):
                    call_command(
                        "set_admin_mfa", email, "--disable", "--reason", "Should be rejected",
                        stdout=StringIO(),
                    )
                if user is not None:
                    user.refresh_from_db()
                    self.assertTrue(user.management_mfa_required)
                    self.assertFalse(user.is_superuser)
                    self.assertEqual(TOTPDevice.objects.filter(user=user).count(), 0)
        self.assertFalse(User.objects.filter(email="missing@example.invalid").exists())
        self.assertFalse(AuditEvent.objects.filter(action="security.admin_mfa_policy_changed").exists())

