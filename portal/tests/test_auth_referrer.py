"""Native HTTPS auth forms keep CSRF protection and hide referrers from third parties."""
import re
from unittest.mock import patch

from django.contrib.auth.tokens import default_token_generator
from django.test import Client, TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from portal.models import User


@override_settings(SECURE_SSL_REDIRECT=False, STAFF_MFA_REQUIRED=True,
    ALLOWED_HOSTS=["testserver"], CSRF_TRUSTED_ORIGINS=["https://testserver"],
    SECURE_REFERRER_POLICY="same-origin",
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AuthReferrerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="referrer-qa@example.invalid", is_staff=True, is_test=True)
        self.assertFalse(self.user.has_usable_password())
        self.client = Client(enforce_csrf_checks=True)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        self.activation_path = f"/activar/{uid}/{token}/"

    def form_token(self, path):
        response = self.client.get(path, secure=True)
        self.assertEqual(response.status_code, 200)
        form = re.search(r'<form\b[^>]*method="post"[^>]*>(.*?)</form>', response.content.decode(), re.S)
        self.assertIsNotNone(form)
        hidden = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', form.group(1))
        self.assertIsNotNone(hidden)
        self.assertIn("csrftoken", self.client.cookies)
        return hidden.group(1)

    def test_auth_policy_supports_native_forms_without_cross_origin_referrer(self):
        # Referrer Policy's same-origin directive omits the Referer entirely on
        # cross-origin requests; it must not be replaced with origin/unsafe-url.
        # Unlike no-referrer, Fetch preserves Origin on a same-origin form POST.
        # https://www.w3.org/TR/referrer-policy/#referrer-policy-same-origin
        # https://fetch.spec.whatwg.org/#append-a-request-origin-header
        for path in ("/recuperar-acceso/", "/iniciar-sesion/", self.activation_path,
                     "/activar/invalid/invalid/"):
            with self.subTest(page="activation" if path.startswith("/activar/") else path):
                response = self.client.get(path, secure=True)
                self.assertEqual(response["Referrer-Policy"], "same-origin")
                self.assertEqual(response["Cache-Control"], "private, no-store")
                self.assertIn("form-action 'self'", response["Content-Security-Policy"])

    def test_recovery_accepts_native_same_origin_post_and_https_referer_fallback(self):
        for headers in ({"HTTP_ORIGIN": "https://testserver"},
                        {"HTTP_REFERER": "https://testserver/recuperar-acceso/"}):
            with self.subTest(headers=sorted(headers)):
                token = self.form_token("/recuperar-acceso/")
                with patch("portal.auth_views.activation_email") as queue_email:
                    response = self.client.post("/recuperar-acceso/", {
                        "email": self.user.email, "csrfmiddlewaretoken": token,
                    }, secure=True, **headers)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, "/recuperar-acceso/?solicitado=1")
                queue_email.assert_called_once_with(self.user, "recovery")

    def test_null_or_cross_origin_and_missing_csrf_remain_rejected(self):
        token = self.form_token("/recuperar-acceso/")
        cases = [(True, {"HTTP_ORIGIN": "null"}),
                 (True, {"HTTP_ORIGIN": "https://other.example.invalid"}),
                 (True, {"HTTP_REFERER": "https://other.example.invalid/recovery"}),
                 (True, {}),
                 (False, {"HTTP_ORIGIN": "https://testserver"})]
        with patch("portal.auth_views.activation_email") as queue_email:
            for include_token, headers in cases:
                with self.subTest(include_token=include_token, headers=headers):
                    body = {"email": self.user.email}
                    if include_token:
                        body["csrfmiddlewaretoken"] = token
                    response = self.client.post("/recuperar-acceso/", body, secure=True, **headers)
                    self.assertEqual(response.status_code, 403)
        queue_email.assert_not_called()

    def test_initial_staff_password_can_be_set_with_csrf_but_does_not_bypass_mfa(self):
        token = self.form_token(self.activation_path)
        with patch("portal.auth_views.activation_email") as queue_email:
            response = self.client.post(self.activation_path, {
                "csrfmiddlewaretoken": token,
                "new_password1": "Synthetic-Test-Access-5872!",
                "new_password2": "Synthetic-Test-Access-5872!",
            }, secure=True, HTTP_ORIGIN="https://testserver")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/panel/seguridad/")
        self.user.refresh_from_db()
        self.assertTrue(self.user.has_usable_password())
        self.assertTrue(self.user.email_verified)
        admin_response = self.client.get("/admin/", secure=True)
        self.assertEqual(admin_response.status_code, 302)
        self.assertEqual(admin_response.url, "/panel/seguridad/?next=/admin/")
        self.assertContains(self.client.get(self.activation_path, secure=True), "Este enlace venció o ya se utilizó")
        queue_email.assert_not_called()
