"""Management remains reachable from the configuration area without role changes."""
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from portal.models import PlatformSettings, User


@override_settings(SECURE_SSL_REDIRECT=False, STAFF_MFA_REQUIRED=True,
    STORAGES={'default': {'BACKEND': 'portal.storage.PrivateStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class AdminReturnNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(email='return-admin@example.invalid', password=None)
        cls.limited = User.objects.create_user(email='return-limited@example.invalid', password=None, is_staff=True)
        cls.limited.user_permissions.add(Permission.objects.get(content_type__app_label='portal', codename='view_category'))
        PlatformSettings.objects.create(pk=1)

    def verify(self, user):
        self.client.force_login(user)
        device = TOTPDevice.objects.create(user=user, name='Synthetic test device', confirmed=True)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def test_configuration_lists_forms_history_and_password_page_return_to_operations(self):
        self.verify(self.admin)
        for path in ('/admin/', '/admin/portal/platformsettings/1/change/',
                     '/admin/portal/category/', '/admin/portal/category/add/',
                     '/admin/portal/auditevent/', '/admin/password_change/'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="imc-admin-return-link" href="/operaciones/"')
                self.assertContains(response, 'Volver al panel administrativo')
        self.assertEqual(self.client.get('/operaciones/').status_code, 200)

    def test_limited_staff_gets_accessible_home_without_operational_permission(self):
        self.verify(self.limited)
        response = self.client.get('/admin/portal/category/')
        self.assertContains(response, 'class="imc-admin-return-link" href="/admin/"')
        self.assertNotContains(response, 'Volver al panel administrativo')
        self.assertEqual(self.client.get('/operaciones/').status_code, 403)

    def test_new_link_does_not_skip_mfa(self):
        self.client.force_login(self.admin)
        response = self.client.get('/admin/portal/platformsettings/1/change/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/panel/seguridad/?next='))
        self.assertTrue(self.client.get('/operaciones/').url.startswith('/panel/seguridad/?next='))
