"""Correcting registration fields must not consume the account quota."""
from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from portal.models import Notification, PlatformSettings, RateLimit, User


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={
        'default': {'BACKEND': 'portal.storage.PrivateStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class RegistrationFrictionTests(TestCase):
    def setUp(self):
        PlatformSettings.objects.create(pk=1, registration_open=True)

    def payload(self, **changes):
        return {
            'first_name': 'Ana', 'last_name': 'Prueba',
            'email': 'registration-correction@example.invalid',
            'phone_prefix': '+591', 'phone_national': '71234567',
            'company': 'Maquinaria de prueba', 'contact_preference': 'whatsapp',
            'password1': 'Synthetic-Registration-291!',
            'password2': 'Synthetic-Registration-291!', 'terms': 'on',
            **changes,
        }

    def test_five_form_corrections_do_not_block_a_valid_registration(self):
        for _ in range(5):
            response = self.client.post('/registro/', self.payload(last_name=''))
            self.assertEqual(response.status_code, 200)
            self.assertIn('last_name', response.context['form'].errors)
            self.assertFalse(User.objects.exists())
            self.assertFalse(Notification.objects.exists())
        response = self.client.post('/registro/', self.payload())
        self.assertRedirects(response, '/panel/', fetch_redirect_response=False)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(kind='verify').count(), 1)

    def test_five_created_accounts_still_exhaust_the_shared_connection_quota(self):
        for number in range(5):
            response = Client().post('/registro/', self.payload(email=f'account-{number}@example.invalid'))
            self.assertRedirects(response, '/panel/', fetch_redirect_response=False)
        response = Client().post('/registro/', self.payload())
        self.assertContains(response, 'Inténtalo de nuevo en una hora.')
        self.assertEqual(User.objects.count(), 5)
        self.assertEqual(Notification.objects.filter(kind='verify').count(), 5)
        self.assertEqual(response.context['form']['first_name'].value(), 'Ana')
        self.assertEqual(response.context['form']['company'].value(), 'Maquinaria de prueba')
        self.assertEqual(response.context['form']['phone_national'].value(), '71234567')

    def test_attempt_limit_cannot_be_bypassed_by_correcting_the_last_form(self):
        for _ in range(30):
            response = self.client.post('/registro/', self.payload(last_name=''))
            self.assertNotIn('15 minutos', str(response.context['form'].non_field_errors()))
        invalid = self.client.post('/registro/', self.payload(last_name=''))
        self.assertContains(invalid, 'Inténtalo de nuevo en 15 minutos.')
        valid = self.client.post('/registro/', self.payload())
        self.assertContains(valid, 'Inténtalo de nuevo en 15 minutos.')
        self.assertFalse(User.objects.exists())
        self.assertFalse(Notification.objects.exists())
        RateLimit.objects.update(window_start=timezone.now() - timedelta(minutes=16))
        retry = self.client.post('/registro/', self.payload())
        self.assertRedirects(retry, '/panel/', fetch_redirect_response=False)

    def test_invalid_form_preserves_contact_and_safe_publication_destination(self):
        target = '/panel/maquinarias/nueva/'
        response = self.client.post('/registro/', self.payload(last_name='', next=target))
        self.assertEqual(response.context['form']['email'].value(), self.payload()['email'])
        self.assertContains(response, f'name="next" value="{target}"')
        self.assertNotContains(response, self.payload()['password1'])
        response = self.client.post('/registro/', self.payload(next='https://outside.example/'))
        self.assertRedirects(response, '/panel/', fetch_redirect_response=False)
