"""An existing session can request its own password link without bypassing MFA."""
import re

from django.test import Client, TestCase, override_settings
from django_otp.plugins.otp_totp.models import TOTPDevice

from portal.models import Notification, User


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False,
                   ALLOWED_HOSTS=['testserver'],
                   STORAGES={'default': {'BACKEND': 'portal.storage.PrivateStorage'},
                             'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class AuthenticatedRecoveryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser(email='own-admin@example.invalid', password='Synthetic-Old-8927!')
        self.other = User.objects.create_user(email='other-admin@example.invalid', password='Synthetic-Other-8927!')
        self.client.force_login(self.owner)

    def test_request_uses_only_session_account_and_preserves_password_and_mfa(self):
        prior = self.owner.password
        response = self.client.post('/panel/seguridad/?next=/admin/portal/lead/', {
            'action': 'recover_password', 'email': self.other.email, 'user': str(self.other.pk),
            'new_password1': 'Untrusted-new-1298!', 'new_password2': 'Untrusted-new-1298!',
        })
        self.assertRedirects(response, '/panel/seguridad/?next=/admin/portal/lead/', fetch_redirect_response=False)
        notice = Notification.objects.get(kind='recovery')
        self.assertEqual(notice.user_id, self.owner.pk)
        self.assertEqual(notice.status, 'pending')
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.password, prior)
        self.assertFalse(TOTPDevice.objects.get(user=self.owner, name='IMC').confirmed)
        self.assertEqual(self.client.get('/admin/portal/lead/').status_code, 302)

    def test_recovery_is_bounded_per_account_and_not_repeated_by_get(self):
        for _ in range(4):
            self.client.post('/panel/seguridad/', {'action': 'recover_password'})
        self.assertEqual(Notification.objects.filter(user=self.owner, kind='recovery').count(), 3)
        self.client.get('/panel/seguridad/')
        self.assertEqual(Notification.objects.filter(user=self.owner, kind='recovery').count(), 3)

    def test_authenticated_recovery_requires_csrf_and_a_session(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post('/panel/seguridad/', {'action': 'recover_password'})
        self.assertIn(response.status_code, (302, 403))
        client.force_login(self.owner)
        self.assertEqual(client.post('/panel/seguridad/', {'action': 'recover_password'}).status_code, 403)
        page = client.get('/panel/seguridad/')
        csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
        response = client.post('/panel/seguridad/', {'action': 'recover_password', 'csrfmiddlewaretoken': csrf})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Notification.objects.filter(kind='recovery').count(), 1)
