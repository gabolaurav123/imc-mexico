"""Email login identifiers must fit every address accepted at registration."""
from django.contrib.auth.models import AbstractUser
from django.test import Client, TestCase, override_settings

from portal.forms import RegisterForm
from portal.models import PlatformSettings, User


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={
        'default': {'BACKEND': 'portal.storage.PrivateStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class LongEmailRegistrationTests(TestCase):
    def setUp(self):
        PlatformSettings.objects.create(pk=1, registration_open=True)

    def payload(self, email):
        return {
            'first_name': 'Ana', 'last_name': 'Prueba', 'email': email,
            'phone_prefix': '+591', 'phone_national': '71234567',
            'contact_preference': 'email', 'password1': 'Synthetic-Email-782!',
            'password2': 'Synthetic-Email-782!', 'terms': 'on',
        }

    def test_long_email_registers_and_logs_in_without_truncation(self):
        addresses = [
            'a' * 48 + '@' + 'b' * 50 + '.' + 'c' * 50 + '.example.com',
            'a' * 64 + '@' + 'b' * 63 + '.' + 'c' * 63 + '.' + 'd' * 61,
        ]
        self.assertEqual(len(addresses[-1]), 254)
        for email in addresses:
            with self.subTest(length=len(email)):
                self.assertGreater(len(email), 150)
                response = Client().post('/registro/', self.payload(email))
                self.assertRedirects(response, '/panel/', fetch_redirect_response=False)
                user = User.objects.get(email=email)
                self.assertEqual(user.username, email)
                # SQLite does not enforce varchar length, so validate the
                # actual model field as well as the full authentication flow.
                User._meta.get_field('username').clean(user.username, user)
                client = Client()
                response = client.post('/iniciar-sesion/', {
                    'username': email.upper(), 'password': self.payload(email)['password1'],
                })
                self.assertRedirects(response, '/panel/', fetch_redirect_response=False)
                self.assertEqual(int(client.session['_auth_user_id']), user.pk)

    def test_username_retains_abstract_user_identity_constraints(self):
        field = User._meta.get_field('username')
        inherited = AbstractUser._meta.get_field('username')
        self.assertEqual(field.max_length, User._meta.get_field('email').max_length)
        self.assertEqual(field.max_length, 254)
        self.assertEqual(field.unique, inherited.unique)
        self.assertEqual(field.error_messages, inherited.error_messages)
        self.assertEqual(field.verbose_name, inherited.verbose_name)
        self.assertEqual(field.validators[0], inherited.validators[0])

    def test_email_beyond_database_limit_is_a_form_error(self):
        email = 'a' * 64 + '@' + 'b' * 63 + '.' + 'c' * 63 + '.' + 'd' * 62
        self.assertEqual(len(email), 255)
        form = RegisterForm(self.payload(email))
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)
        self.assertFalse(User.objects.exists())
