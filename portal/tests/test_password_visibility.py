"""All authentication templates load the same progressive password controls."""
from html.parser import HTMLParser
from types import SimpleNamespace

from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from portal.models import PlatformSettings, User
from portal.forms import LoginForm


class Inputs(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.inputs = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            self.inputs.append(dict(attrs))


@override_settings(STAFF_MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False,
    STORAGES={"default":{"BACKEND":"portal.storage.PrivateStorage"},
              "staticfiles":{"BACKEND":"django.contrib.staticfiles.storage.StaticFilesStorage"}})
class PasswordVisibilityTemplateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="password-ui@example.invalid", is_test=True)
        PlatformSettings.objects.create(pk=1, registration_open=True, legal_validated=True)

    def check_form(self, response, count, portal=True):
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertEqual(html.count('portal/password-visibility.js'), 1)
        self.assertEqual(html.count('portal/password-visibility.css'), 1)
        inputs = [field for field in Inputs(html).inputs if field.get("type") == "password"]
        self.assertEqual(len(inputs), count)
        self.assertTrue(all(not field.get("value") for field in inputs))
        if portal:
            self.assertEqual(html.count('class="password-field"'), count)
        return inputs

    def test_public_login_registration_recovery_and_reset_share_assets(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        for path, count in (("/iniciar-sesion/",1),("/registro/",2),("/recuperar-acceso/",0),
                            (f"/activar/{uid}/{token}/",2)):
            with self.subTest(flow="reset" if path.startswith('/activar/') else path):
                inputs = self.check_form(self.client.get(path), count)
                self.assertTrue(all(field.get("autocomplete") in {"current-password","new-password"} for field in inputs))

    def test_security_change_form_keeps_current_and_new_password_widgets(self):
        self.client.force_login(self.user)
        inputs = self.check_form(self.client.get("/panel/seguridad/"), 3)
        self.assertEqual({field["name"] for field in inputs}, {"old_password","new_password1","new_password2"})
        self.assertEqual([field["autocomplete"] for field in inputs], ["current-password","new-password","new-password"])

    def test_admin_creation_and_password_change_also_load_controls(self):
        admin = User.objects.create_superuser(email="password-admin@example.invalid", password="Synthetic-Admin-123!")
        self.client.force_login(admin)
        for path in ("/admin/portal/user/add/", f"/admin/portal/user/{self.user.pk}/password/"):
            with self.subTest(page="change" if path.endswith("/password/") else "add"):
                self.check_form(self.client.get(path), 2, portal=False)

    def test_invalid_form_does_not_render_submitted_passwords(self):
        first, second = "Synthetic-Never-Echo-1!", "Synthetic-Never-Echo-2!"
        form = SetPasswordForm(self.user, {"new_password1":first,"new_password2":second})
        self.assertFalse(form.is_valid())
        html = render_to_string("portal/form_fields.html", {"form":form})
        self.assertNotIn(first, html)
        self.assertNotIn(second, html)
        self.assertEqual(html.count('class="password-field"'), 2)
        self.assertIn('role="alert"', html)

    def test_common_login_explains_shared_access_and_links_administration(self):
        response = self.client.get("/iniciar-sesion/")
        self.assertContains(response, "ACCESO A IMC MÉXICO")
        self.assertContains(response, 'href="/administracion/"')
        self.assertContains(response, "Este acceso sirve para anunciantes y para el equipo de IMC")

    def test_dedicated_admin_template_uses_management_copy_and_masked_credentials(self):
        html = render_to_string("portal/auth.html", {"admin_access": True, "title": "Acceso administrativo",
            "submit_label": "Entrar a administración", "form": LoginForm(),
            "request": SimpleNamespace(path="/administracion/"), "csrf_token": "a" * 64})
        self.assertIn("ADMINISTRACIÓN IMC MÉXICO", html)
        self.assertIn("Entrar a administración", html)
        self.assertIn("código de tu aplicación de autenticación", html)
        self.assertIn('href="/recuperar-acceso/"', html)
        self.assertNotIn("Todo empieza", html)
        self.assertNotIn("Sube tus fotos", html)
        self.assertNotIn("PORTAL DE ANUNCIANTES", html)
        self.assertNotIn("Anunciar mi maquinaria", html)
        passwords = [field for field in Inputs(html).inputs if field.get("type") == "password"]
        self.assertEqual(len(passwords), 1)
        self.assertFalse(passwords[0].get("value"))
