"""Advertisers can choose and later change shorter passwords without losing access."""
from django.contrib.auth.tokens import default_token_generator
from django.test import Client, TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from portal.forms import RegisterForm
from portal.models import AuditEvent, PlatformSettings, User


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STAFF_MFA_REQUIRED=True,
    ALLOWED_HOSTS=["testserver"],
    STORAGES={
        "default": {"BACKEND": "portal.storage.PrivateStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class AccountPasswordFlowTests(TestCase):
    def setUp(self):
        PlatformSettings.objects.create(pk=1, registration_open=True)

    def registration(self, password="Nube7rio", **changes):
        return {
            "first_name": "Ana", "last_name": "Prueba", "email": "short-access@example.invalid",
            "phone_prefix": "+52", "phone_national": "55 1234 5678",
            "contact_preference": "email", "password1": password, "password2": password,
            "terms": "on", **changes,
        }

    def assert_login(self, user, password):
        self.client.logout()
        response = self.client.post("/iniciar-sesion/", {"username": user.email, "password": password})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        return response

    def activation_path(self, user):
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        return f"/activar/{uid}/{token}/"

    def test_registration_accepts_eight_characters_and_logs_in_with_same_password(self):
        response = self.client.post("/registro/", self.registration())
        self.assertRedirects(response, "/panel/", fetch_redirect_response=False)
        user = User.objects.get(email="short-access@example.invalid")
        self.assertTrue(user.check_password("Nube7rio"))
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assert_login(user, "Nube7rio")

    def test_registration_rejects_seven_characters_and_keeps_entered_contact(self):
        response = self.client.post("/registro/", self.registration("Nube7ri"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)
        self.assertEqual(response.context["form"]["email"].value(), "short-access@example.invalid")
        self.assertFalse(User.objects.exists())

    def test_registration_help_and_browser_minimum_match_the_eight_character_policy(self):
        response = self.client.get("/registro/")
        form = response.context["form"]
        for name in ("password1", "password2"):
            self.assertEqual(form.fields[name].widget.attrs["minlength"], 8)
        self.assertContains(response, "Mínimo 8 caracteres")
        self.assertContains(response, "Podrás cambiarla después desde Mi cuenta")
        self.assertNotContains(response, "Mínimo 12 caracteres")

    def test_change_and_recovery_help_match_each_account_policy_without_limiting_login(self):
        for staff, minimum in ((False, 8), (True, 12)):
            with self.subTest(staff=staff):
                user = User.objects.create_user(email=f"hints-{staff}@example.invalid", is_staff=staff)
                self.client.force_login(user)
                security = self.client.get("/panel/seguridad/")
                form = security.context["password_form"]
                self.assertNotIn("minlength", form.fields["old_password"].widget.attrs)
                for name in ("new_password1", "new_password2"):
                    self.assertEqual(form.fields[name].widget.attrs["minlength"], minimum)
                self.assertContains(security, f"Mínimo {minimum} caracteres")
                reset = Client().get(self.activation_path(user))
                for name in ("new_password1", "new_password2"):
                    self.assertEqual(reset.context["form"].fields[name].widget.attrs["minlength"], minimum)
                self.assertContains(reset, f"Mínimo {minimum} caracteres")
        login = Client().get("/iniciar-sesion/")
        self.assertNotIn("minlength", login.context["form"].fields["password"].widget.attrs)

    def test_easier_length_does_not_accept_common_numeric_or_identity_passwords(self):
        for password in ("password", "12345678", "87650123", "short-access@example.invalid"):
            with self.subTest(password_kind="numeric" if password.isdigit() else "common_or_identity"):
                form = RegisterForm(self.registration(password))
                self.assertFalse(form.is_valid())
                self.assertIn("password2", form.errors)
        self.assertFalse(User.objects.exists())

    def test_registration_and_login_preserve_boundary_spaces_exactly(self):
        password = " Nube7rio "
        response = self.client.post("/registro/", self.registration(password))
        self.assertRedirects(response, "/panel/", fetch_redirect_response=False)
        user = User.objects.get(email="short-access@example.invalid")
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.check_password(password.strip()))
        self.assert_login(user, password)
        self.client.logout()
        response = self.client.post("/iniciar-sesion/", {"username": user.email, "password": password.strip()})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_change_accepts_eight_characters_preserves_session_and_revokes_old_access(self):
        user = User.objects.create_user(email="change-access@example.invalid", password="Existing-access-739!")
        other_session = Client()
        other_session.force_login(user)
        self.client.force_login(user)
        response = self.client.post("/panel/seguridad/", {
            "action": "password", "old_password": "Existing-access-739!",
            "new_password1": "Nube7rio", "new_password2": "Nube7rio",
        })
        self.assertRedirects(response, "/panel/seguridad/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/panel/").status_code, 200)
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertEqual(other_session.get("/panel/").status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password("Nube7rio"))
        self.assertFalse(user.check_password("Existing-access-739!"))
        self.assertTrue(AuditEvent.objects.filter(actor=user, action="password.changed").exists())
        self.assert_login(user, "Nube7rio")

    def test_password_change_requires_current_password_and_does_not_save_invalid_input(self):
        user = User.objects.create_user(email="invalid-change@example.invalid", password="Existing-access-739!")
        self.client.force_login(user)
        for old, first, second, error in (
            ("wrong", "Nube7rio", "Nube7rio", "old_password"),
            ("Existing-access-739!", "Nube7ri", "Nube7ri", "new_password2"),
            ("Existing-access-739!", "Nube7rio", "Rio7nube", "new_password2"),
        ):
            with self.subTest(error=error):
                response = self.client.post("/panel/seguridad/", {
                    "action": "password", "old_password": old,
                    "new_password1": first, "new_password2": second,
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn(error, response.context["password_form"].errors)
                self.assertContains(response, 'class="surface security-password" open')
                user.refresh_from_db()
                self.assertTrue(user.check_password("Existing-access-739!"))
                self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))

    def test_password_change_preserves_boundary_spaces_in_current_and_new_passwords(self):
        user = User.objects.create_user(email="space-change@example.invalid", password=" Nube7rio ")
        self.client.force_login(user)
        response = self.client.post("/panel/seguridad/", {
            "action": "password", "old_password": " Nube7rio ",
            "new_password1": " Rio7nube ", "new_password2": " Rio7nube ",
        })
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password(" Rio7nube "))
        self.assertFalse(user.check_password("Rio7nube"))
        self.assert_login(user, " Rio7nube ")

    def test_reset_accepts_eight_characters_and_keeps_token_one_use(self):
        user = User.objects.create_user(email="short-reset@example.invalid", password="Existing-access-739!")
        path = self.activation_path(user)
        response = self.client.post(path, {"new_password1": "Nube7rio", "new_password2": "Nube7rio"})
        self.assertRedirects(response, "/panel/", fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertTrue(user.check_password("Nube7rio"))
        self.assertFalse(user.check_password("Existing-access-739!"))
        self.assertContains(self.client.get(path), "Este enlace venció o ya se utilizó")
        self.assert_login(user, "Nube7rio")

    def test_reset_rejects_seven_characters_without_consuming_the_token(self):
        user = User.objects.create_user(email="invalid-reset@example.invalid", password="Existing-access-739!")
        path = self.activation_path(user)
        response = self.client.post(path, {"new_password1": "Nube7ri", "new_password2": "Nube7ri"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("new_password2", response.context["form"].errors)
        user.refresh_from_db()
        self.assertTrue(user.check_password("Existing-access-739!"))
        self.assertFalse(user.email_verified)
        response = self.client.post(path, {"new_password1": "Nube7rio", "new_password2": "Nube7rio"})
        self.assertEqual(response.status_code, 302)

    def test_reset_preserves_boundary_spaces_for_subsequent_login(self):
        user = User.objects.create_user(email="space-reset@example.invalid", password="Existing-access-739!")
        response = self.client.post(self.activation_path(user), {
            "new_password1": " Nube7rio ", "new_password2": " Nube7rio ",
        })
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password(" Nube7rio "))
        self.assertFalse(user.check_password("Nube7rio"))
        self.assert_login(user, " Nube7rio ")

    def test_staff_reset_retains_twelve_character_requirement_and_mfa(self):
        user = User.objects.create_user(email="staff-reset@example.invalid", password="Existing-access-739!", is_staff=True)
        path = self.activation_path(user)
        response = self.client.post(path, {"new_password1": "Nube7rio", "new_password2": "Nube7rio"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("new_password2", response.context["form"].errors)
        user.refresh_from_db()
        self.assertTrue(user.check_password("Existing-access-739!"))
        response = self.client.post(path, {"new_password1": "Nube7rio9so", "new_password2": "Nube7rio9so"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("new_password2", response.context["form"].errors)
        response = self.client.post(path, {"new_password1": "Nube7rio9sol", "new_password2": "Nube7rio9sol"})
        self.assertRedirects(response, "/panel/seguridad/", fetch_redirect_response=False)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/panel/seguridad/"))
