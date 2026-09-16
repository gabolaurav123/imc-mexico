"""Email configuration diagnostics must stay offline and never expose secrets."""
from io import StringIO
import json
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings


@override_settings(DEBUG=False, EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                   EMAIL_HOST="smtp.resend.com", EMAIL_PORT=465, EMAIL_HOST_USER="PRIVATE-SMTP-LOGIN-123",
                   EMAIL_HOST_PASSWORD="PRIVATE-SMTP-PASSWORD-456", EMAIL_USE_TLS=False, EMAIL_USE_SSL=True,
                   EMAIL_TIMEOUT=20, DEFAULT_FROM_EMAIL="IMC México <avisos@example.com>", EMAIL_REPLY_TO="",
                   PUBLIC_URL="https://portal.example.com")
class EmailConfigurationTests(SimpleTestCase):
    def report(self, *, error=False):
        output = StringIO()
        with patch("socket.create_connection", side_effect=AssertionError("Network must not be used")) as connection, \
                patch("socket.getaddrinfo", side_effect=AssertionError("DNS must not be used")) as dns, \
                patch("smtplib.SMTP", side_effect=AssertionError("SMTP must not be used")) as smtp, \
                patch("smtplib.SMTP_SSL", side_effect=AssertionError("SMTP must not be used")) as smtp_ssl:
            if error:
                with self.assertRaises(CommandError):
                    call_command("check_email_config", "--json", stdout=output)
            else:
                call_command("check_email_config", "--json", stdout=output)
        for mocked in (connection, dns, smtp, smtp_ssl):
            mocked.assert_not_called()
        raw = output.getvalue()
        self.assertNotIn("PRIVATE-SMTP-LOGIN-123", raw)
        self.assertNotIn("PRIVATE-SMTP-PASSWORD-456", raw)
        return json.loads(raw)

    def test_valid_config_reports_only_presence_of_credentials_without_claiming_delivery(self):
        report = self.report()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["scope"], "configuration_only")
        self.assertEqual(report["configuration"]["smtp_host"], "smtp.resend.com")
        self.assertTrue(report["configuration"]["smtp_username_configured"])
        self.assertTrue(report["configuration"]["smtp_password_configured"])
        self.assertEqual(report["configuration"]["sender_scope"], "unverified")
        self.assertTrue(all(value is False for value in report["verification"].values()))

    def test_resend_dev_is_test_only_not_verified_general_delivery(self):
        with override_settings(DEFAULT_FROM_EMAIL="IMC México <onboarding@resend.dev>"):
            report = self.report()
        self.assertEqual(report["status"], "warnings")
        self.assertEqual(report["configuration"]["sender_scope"], "test_only")
        self.assertIn("sender_resend_test_only", [item["code"] for item in report["issues"]])
        self.assertFalse(report["verification"]["sender_domain_verified"])

    def test_reply_to_accepts_one_named_mailbox_and_rejects_lists_or_header_injection(self):
        with override_settings(EMAIL_REPLY_TO='"Equipo, IMC" <soporte@example.com>'):
            report = self.report()
            self.assertIn("soporte@example.com", report["configuration"]["reply_to"])
        for invalid in ("one@example.com, two@example.com", "support@example.com\r\nBcc: hidden@example.com", "not-an-email"):
            with self.subTest(invalid=invalid), override_settings(EMAIL_REPLY_TO=invalid):
                report = self.report(error=True)
                self.assertEqual(report["configuration"]["reply_to"], "(invalid)")
                self.assertIn("reply_to_invalid", [item["code"] for item in report["issues"]])
                self.assertNotIn("hidden@example.com", json.dumps(report))

    def test_conflicting_tls_and_ssl_and_missing_credentials_are_errors(self):
        with override_settings(EMAIL_USE_TLS=True, EMAIL_HOST_PASSWORD=""):
            report = self.report(error=True)
        codes = {item["code"] for item in report["issues"]}
        self.assertTrue({"smtp_tls_ssl_conflict", "smtp_credentials_incomplete"}.issubset(codes))

    def test_local_backend_is_not_production_delivery_and_development_is_explicit_warning(self):
        for name in ("console", "dummy", "locmem", "filebased"):
            with self.subTest(backend=name), override_settings(EMAIL_BACKEND=f"django.core.mail.backends.{name}.EmailBackend"):
                self.assertEqual(self.report(error=True)["status"], "errors")
                with override_settings(DEBUG=True, PUBLIC_URL="http://localhost:8000"):
                    self.assertEqual(self.report()["status"], "warnings")

    def test_bad_public_url_never_prints_password_or_activation_token(self):
        invalid_urls = ("https://private-user:PRIVATE-URL-PASSWORD@portal.example.com",
                        "https://portal.example.com/activar/uid/PRIVATE-ACTIVATION-TOKEN/",
                        "https://portal.example.com/?token=PRIVATE-ACTIVATION-TOKEN",
                        "http://portal.example.com", "https://127.0.0.1")
        for url in invalid_urls:
            with self.subTest(url=url), override_settings(PUBLIC_URL=url):
                report = self.report(error=True)
                encoded = json.dumps(report)
                self.assertNotIn("PRIVATE-URL-PASSWORD", encoded)
                self.assertNotIn("PRIVATE-ACTIVATION-TOKEN", encoded)
                self.assertFalse(report["configuration"]["public_url_valid"])

    def test_invalid_host_sender_port_and_no_encryption_are_reported_without_echoing_values(self):
        with override_settings(EMAIL_HOST="smtp://name:PRIVATE-SMTP-PASSWORD-456@example.com", EMAIL_PORT=0,
                               DEFAULT_FROM_EMAIL="notice@example.com\nBcc: secret@example.com", EMAIL_USE_SSL=False):
            report = self.report(error=True)
        codes = {item["code"] for item in report["issues"]}
        self.assertTrue({"smtp_host_invalid", "smtp_port_invalid", "sender_invalid", "smtp_unencrypted"}.issubset(codes))
        self.assertNotIn("secret@example.com", json.dumps(report))

    def test_human_output_redacts_credentials_and_states_checks_not_performed(self):
        output = StringIO()
        call_command("check_email_config", stdout=output)
        text = output.getvalue()
        self.assertIn("smtp_username_configured: True", text)
        self.assertIn("Sin conexión ni envío", text)
        self.assertNotIn("PRIVATE-SMTP-LOGIN-123", text)
        self.assertNotIn("PRIVATE-SMTP-PASSWORD-456", text)

    def test_worker_once_describes_backend_acceptance_not_delivery(self):
        output = StringIO()
        with patch("portal.management.commands.runworker.signal.signal"), \
                patch("portal.management.commands.runworker.close_old_connections"), \
                patch("portal.management.commands.runworker.process_next_job", return_value=False), \
                patch("portal.management.commands.runworker.process_notifications", return_value=2), \
                patch("portal.management.commands.runworker.purge_expired_accesses", return_value=0):
            call_command("runworker", "--once", stdout=output)
        self.assertIn("Avisos aceptados por backend: 2", output.getvalue())
        self.assertNotIn("entregados", output.getvalue())
