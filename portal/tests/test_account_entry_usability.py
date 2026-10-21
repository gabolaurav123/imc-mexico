"""Account links lead to usable forms with accurate password instructions."""
from django.test import TestCase, override_settings

from portal.models import User


@override_settings(
    SECURE_SSL_REDIRECT=False, STAFF_MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={
        'default': {'BACKEND': 'portal.storage.PrivateStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class AccountEntryUsabilityTests(TestCase):
    def test_profile_links_directly_to_an_open_password_form(self):
        user = User.objects.create_user(email='profile-access@example.invalid', password='Existing-access-739!')
        self.client.force_login(user)
        response = self.client.get('/panel/perfil/')
        self.assertContains(response, '/panel/seguridad/?contrasena=1#cambiar-contrasena')
        response = self.client.get('/panel/seguridad/?contrasena=1')
        self.assertContains(response, 'id="cambiar-contrasena" class="surface security-password" open')
        self.assertContains(response, 'Mínimo 8 caracteres')
        self.assertEqual(response.context['password_form'].fields['old_password'].widget.attrs.get('minlength'), None)

    def test_expired_link_offers_recovery_without_a_login_detour(self):
        response = self.client.get('/activar/invalid/invalid/')
        self.assertContains(response, 'href="/recuperar-acceso/">Solicitar un nuevo enlace')
        self.assertNotContains(response, 'name="new_password1"')
        self.assertEqual(self.client.get('/recuperar-acceso/').status_code, 200)

    def test_admin_password_form_uses_the_target_accounts_requirement(self):
        admin = User.objects.create_superuser(email='policy-admin@example.invalid', password='Existing-admin-739!')
        advertiser = User.objects.create_user(email='policy-advertiser@example.invalid')
        self.client.force_login(admin)
        for target, minimum in ((advertiser, 8), (admin, 12)):
            with self.subTest(minimum=minimum):
                response = self.client.get(f'/admin/portal/user/{target.pk}/password/')
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'Mínimo {minimum} caracteres')
                self.assertContains(response, f'minlength="{minimum}"')

    def test_management_entry_does_not_promise_a_disabled_authenticator(self):
        response = self.client.get('/administracion/')
        self.assertContains(response, 'correo y la contraseña de tu cuenta administrativa')
        self.assertNotContains(response, 'te pediremos el código de tu aplicación')
