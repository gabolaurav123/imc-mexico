"""Dedicated management access still uses password, account permissions and OTP."""
from urllib.parse import parse_qs, urlencode, urlsplit

from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from portal.models import RateLimit, User


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False, DEBUG=False,
    ALLOWED_HOSTS=['testserver'], PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'portal.storage.PrivateStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class AdministrationEntryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = 'Local-administration-test-749!'
        cls.admin = User.objects.create_superuser(email='admin-entry@example.invalid', password=cls.password)
        cls.owner = User.objects.create_user(email='owner-entry@example.invalid', password=cls.password)
        cls.limited = User.objects.create_user(email='limited-entry@example.invalid', password=cls.password, is_staff=True)
        cls.limited.user_permissions.add(Permission.objects.get(content_type__app_label='portal', codename='view_lead'))

    def post_login(self, user, *, next_url=None):
        query = '?' + urlencode({'next': next_url}) if next_url else ''
        return self.client.post('/administracion/' + query,
            {'username': '  ' + user.email.upper() + '  ', 'password': self.password})

    def assert_mfa(self, response, destination):
        self.assertEqual(response.status_code, 302)
        parsed = urlsplit(response.url)
        self.assertEqual(parsed.path, '/panel/seguridad/')
        self.assertEqual(parse_qs(parsed.query), {'next': [destination]})

    def test_entry_has_explicit_management_context_and_private_headers(self):
        response = self.client.get('/administracion/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['admin_access'])
        self.assertContains(response, 'Acceso administrativo')
        self.assertContains(response, 'Entrar a administración')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    def test_staff_password_login_ignores_advertiser_or_external_next_and_requires_real_otp(self):
        for next_url in ('/panel/?modo=anunciante', '/panel/maquinarias/', 'https://other.example/'):
            with self.subTest(next_url=next_url):
                self.client.logout()
                response = self.post_login(self.admin, next_url=next_url)
                self.assert_mfa(response, '/operaciones/')
                self.assertEqual(self.client.session['_auth_user_id'], str(self.admin.pk))
                self.assertNotIn(DEVICE_ID_SESSION_KEY, self.client.session)
                self.assert_mfa(self.client.get('/admin/portal/lead/'), '/admin/portal/lead/')
        security_url = response.url
        self.client.get(security_url)
        device = TOTPDevice.objects.get(user=self.admin, name='IMC')
        token = f'{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}'
        response = self.client.post(security_url, {'action': 'otp', 'token': token})
        self.assertRedirects(response, '/operaciones/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/operaciones/').status_code, 200)

    def test_authenticated_staff_always_reenters_management_with_existing_mfa_gate(self):
        self.client.force_login(self.admin)
        self.assert_mfa(self.client.get('/administracion/?next=/panel/'), '/operaciones/')
        device = TOTPDevice.objects.create(user=self.admin, name='IMC', confirmed=True)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        self.assertRedirects(self.client.get('/administracion/?next=/panel/?modo=anunciante'),
                             '/operaciones/', fetch_redirect_response=False)

    def test_nonstaff_credentials_are_rejected_without_creating_or_elevating_session(self):
        response = self.post_login(self.owner)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Esta cuenta no tiene acceso administrativo')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_staff)
        self.assertFalse(self.owner.is_superuser)
        self.assertFalse(TOTPDevice.objects.filter(user=self.owner).exists())
        self.client.force_login(self.owner)
        response = self.client.get('/administracion/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tu sesión actual no tiene permisos administrativos')
        self.assertEqual(self.client.session['_auth_user_id'], str(self.owner.pk))
        self.assertEqual(self.client.get('/operaciones/').status_code, 403)

    def test_limited_staff_is_sent_to_admin_without_gaining_operations_permission(self):
        self.assert_mfa(self.post_login(self.limited), '/admin/')
        self.limited.refresh_from_db()
        self.assertFalse(self.limited.has_perm('portal.operate_platform'))
        User.objects.filter(pk=self.limited.pk).update(is_active=False)
        self.client.logout()
        self.assertEqual(self.post_login(self.limited).status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_both_login_routes_share_account_throttle_and_admin_entry_enforces_csrf(self):
        for attempt in range(12):
            route = '/administracion/' if attempt % 2 else '/iniciar-sesion/'
            response = self.client.post(route, {'username': self.admin.email, 'password': 'incorrect-local-password'})
            self.assertEqual(response.status_code, 200)
        response = self.post_login(self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Se alcanzó el límite de intentos')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(RateLimit.objects.count(), 2)
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/administracion/', {'username': self.admin.email, 'password': self.password}).status_code, 403)
