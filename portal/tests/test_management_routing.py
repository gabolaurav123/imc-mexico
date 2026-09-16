"""Management entry is discoverable without weakening model permissions or MFA."""
from urllib.parse import parse_qs, urlencode, urlsplit

from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from portal.models import Machine, User


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False, DEBUG=False,
    ALLOWED_HOSTS=['testserver'],
    STORAGES={'default': {'BACKEND': 'portal.storage.PrivateStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ManagementRoutingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = 'Local-management-test-974!'
        cls.owner = User.objects.create_user(email='advertiser-routing@example.invalid', password=cls.password)
        cls.admin = User.objects.create_superuser(email='admin-routing@example.invalid', password=cls.password)
        cls.limited = User.objects.create_user(email='limited-routing@example.invalid', password=cls.password, is_staff=True)
        cls.limited.user_permissions.add(Permission.objects.get(content_type__app_label='portal', codename='view_lead'))

    def login_password(self, user, next_url=None):
        query = '?' + urlencode({'next': next_url}) if next_url is not None else ''
        return self.client.post('/iniciar-sesion/' + query, {'username': user.email, 'password': self.password})

    def verified_login(self, user):
        self.client.force_login(user)
        device = TOTPDevice.objects.create(user=user, name='IMC', confirmed=True)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        return device

    def assert_mfa_destination(self, response, destination):
        self.assertEqual(response.status_code, 302)
        parsed = urlsplit(response.url)
        self.assertEqual(parsed.path, '/panel/seguridad/')
        self.assertEqual(parse_qs(parsed.query), {'next': [destination]})

    def test_advertisers_keep_their_existing_home_and_no_management_capabilities(self):
        self.assertRedirects(self.login_password(self.owner), '/panel/', fetch_redirect_response=False)
        response = self.client.get('/panel/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['is_management_user'])
        self.assertFalse(response.context['is_advertiser_mode'])
        self.assertEqual(self.client.get('/operaciones/').status_code, 403)

    def test_password_login_and_plain_panel_take_admin_to_focused_mfa_onboarding(self):
        self.assert_mfa_destination(self.login_password(self.admin), '/operaciones/')
        self.assert_mfa_destination(self.client.get('/panel/'), '/operaciones/')
        response = self.client.get('/panel/seguridad/?next=/operaciones/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_management_user'])
        self.assertTrue(response.context['needs_management_mfa'])
        self.assertFalse(response.context['verified'])
        self.assertFalse(response.context['is_advertiser_mode'])
        self.assertTrue(response.context['qr'])
        self.assertNotIn('autofocus', response.context['otp_form'].fields['token'].widget.attrs)
        self.assertNotIn('autofocus', response.context['password_form'].fields['old_password'].widget.attrs)
        self.assertFalse(TOTPDevice.objects.get(user=self.admin, name='IMC').confirmed)

    def test_verified_admin_enters_operations_and_authenticated_login_does_not_loop(self):
        self.verified_login(self.admin)
        for path in ('/panel/', '/iniciar-sesion/', '/iniciar-sesion/?next=/iniciar-sesion/'):
            with self.subTest(path=path):
                self.assertRedirects(self.client.get(path), '/operaciones/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/operaciones/').status_code, 200)

    def test_limited_staff_enters_django_admin_without_operational_or_unassigned_permissions(self):
        self.assert_mfa_destination(self.login_password(self.limited), '/admin/')
        self.verified_login(self.limited)
        self.assertRedirects(self.client.get('/panel/'), '/admin/', fetch_redirect_response=False)
        response = self.client.get('/panel/seguridad/')
        self.assertTrue(response.context['is_management_user'])
        self.assertEqual(response.context['management_url'], '/admin/')
        self.assertEqual(self.client.get('/admin/portal/lead/').status_code, 200)
        self.assertEqual(self.client.get('/admin/portal/user/').status_code, 403)
        self.assertEqual(self.client.get('/operaciones/').status_code, 403)
        self.limited.refresh_from_db()
        self.assertFalse(self.limited.has_perm('portal.operate_platform'))
        self.assertFalse(self.limited.is_superuser)

    def test_advertiser_mode_is_explicit_and_still_limits_owned_dashboard_records(self):
        own = Machine.objects.create(owner=self.admin, title='Mi ficha personal')
        other = Machine.objects.create(owner=self.owner, title='Ficha privada de otra cuenta')
        self.client.force_login(self.admin)
        response = self.client.get('/panel/?modo=anunciante')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_advertiser_mode'])
        self.assertContains(response, own.title)
        self.assertNotContains(response, other.title)
        self.assertTrue(self.client.get('/panel/maquinarias/').context['is_advertiser_mode'])
        self.assertFalse(self.client.get('/panel/perfil/').context['is_advertiser_mode'])
        self.assertRedirects(self.login_password(self.admin, '/panel/?modo=anunciante'),
                             '/panel/?modo=anunciante', fetch_redirect_response=False)

    def test_valid_next_survives_mfa_including_its_query_and_real_otp_is_required(self):
        destination = '/admin/portal/lead/?status__exact=new'
        response = self.login_password(self.admin, destination)
        self.assert_mfa_destination(response, destination)
        security_url = response.url
        self.client.get(security_url)
        device = TOTPDevice.objects.get(user=self.admin, name='IMC')
        token = f'{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}'
        response = self.client.post(security_url, {'action': 'otp', 'token': token})
        self.assertRedirects(response, destination, fetch_redirect_response=False)
        self.assertEqual(self.client.get(destination).status_code, 200)
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertFalse(device.verify_token(token))

    def test_external_null_relative_or_recursive_next_never_changes_the_safe_destination(self):
        self.verified_login(self.admin)
        for requested in ('https://evil.example/', '//evil.example/', 'javascript:alert(1)',
                          'null', 'relative/path', '/iniciar-sesion/', '/registro/'):
            with self.subTest(requested=requested):
                response = self.client.get('/iniciar-sesion/?' + urlencode({'next': requested}))
                self.assertRedirects(response, '/operaciones/', fetch_redirect_response=False)
        for requested in ('https://evil.example/', '/panel/seguridad/', '/iniciar-sesion/'):
            with self.subTest(security_next=requested):
                response = self.client.get('/panel/seguridad/?' + urlencode({'next': requested}))
                self.assertEqual(response.context['next_url'], '/operaciones/')

    def test_management_query_cannot_elevate_an_advertiser_and_inactive_staff_cannot_login(self):
        self.assertRedirects(self.login_password(self.owner, '/admin/'), '/panel/', fetch_redirect_response=False)
        response = self.client.get('/admin/', follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(response.redirect_chain), 4)
        self.assertEqual(response.redirect_chain[-1][0], '/panel/')
        self.assertFalse(response.context['is_management_user'])
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_staff)
        self.client.logout()
        User.objects.filter(pk=self.admin.pk).update(is_active=False)
        self.assertEqual(self.login_password(self.admin).status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
