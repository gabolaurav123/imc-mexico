from datetime import timedelta
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from portal.auth_views import activation_email
from portal.emailing import NotificationNotSendable, build_notification_email, notification_context
from portal.models import Machine, Notification, User
from portal.processing import process_notifications


class EmailMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links, self.images, self.tags = [], [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        if tag == "img":
            self.images.append(attrs.get("src", ""))


@override_settings(PUBLIC_URL="https://portal.example.com", DEBUG=False,
    DEFAULT_FROM_EMAIL="IMC México <avisos@example.com>", EMAIL_REPLY_TO="",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SECURE_SSL_REDIRECT=False,
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TransactionalEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="email-qa@example.com", first_name="María")
        self.machine = Machine.objects.create(owner=self.user, title="Equipo de prueba")

    def notice(self, kind="reply", body="Gracias por tus fotografías.\n\nRevisa las observaciones."):
        return Notification.objects.create(user=self.user, machine=self.machine, channel="email",
                                           kind=kind, subject="Una respuesta de IMC México", body=body)

    def test_multipart_mail_keeps_text_brand_logo_and_exact_queued_content(self):
        notice = self.notice()
        body_before = notice.body
        self.assertEqual(process_notifications(), 1)
        notice.refresh_from_db()
        self.assertEqual(notice.body, body_before)
        self.assertEqual(notice.status, "sent")
        self.assertEqual(notice.attempts, 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.user.email])
        self.assertEqual(message.from_email, "IMC México <avisos@example.com>")
        self.assertEqual(message.extra_headers["Auto-Submitted"], "auto-generated")
        self.assertIn("Gracias por tus fotografías.", message.body)
        self.assertIn("Leer y responder:", message.body)
        self.assertNotIn("<table", message.body)
        html = message.alternatives[0].content
        self.assertEqual(message.alternatives[0].mimetype, "text/html")
        self.assertIn("#000033", html)
        self.assertIn("#e38c1a", html)
        parsed = EmailMarkup(html)
        self.assertEqual(parsed.images, ["cid:imc-logo"])
        parts = list(message.message().walk())
        self.assertIn("multipart/alternative", [part.get_content_type() for part in parts])
        logo = next(part for part in parts if part.get_content_type() == "image/png")
        original = Path(__file__).resolve().parents[1] / "static" / "portal" / "imc-logo.png"
        self.assertEqual(logo.get_payload(decode=True), original.read_bytes())
        self.assertEqual(logo["Content-ID"], "<imc-logo>")
        self.assertTrue(logo["Content-Disposition"].startswith("inline"))

    def test_user_content_is_text_not_markup_or_a_button_destination(self):
        self.user.first_name = '<img src="https://evil.example/tracker">'
        self.user.save()
        notice = self.notice(body='<script>alert(1)</script>\n\n<a href="javascript:alert(2)">Texto</a> & "comillas"')
        notice.subject = '<a href="https://evil.example">Asunto</a>\r\nBcc: injected@example.com'
        notice.save()
        message = build_notification_email(notice)
        parsed = EmailMarkup(message.alternatives[0].content)
        self.assertNotIn("script", parsed.tags)
        self.assertEqual(parsed.images, ["cid:imc-logo"])
        self.assertTrue(all(urlsplit(link).netloc == "portal.example.com" for link in parsed.links))
        self.assertIn("&lt;script&gt;", message.alternatives[0].content)
        self.assertIn('<script>alert(1)</script>', message.body)
        self.assertNotIn("\n", message.subject)
        self.assertNotIn("Bcc", message.message())

    def test_buttons_follow_notification_kind_without_claiming_publication(self):
        paths = {"submission": "/panel/solicitudes/", "review": "/panel/solicitudes/",
                 "reply": f"/panel/mensajes/?maquinaria={self.machine.pk}",
                 "reminder": f"/panel/maquinarias/{self.machine.pk}/",
                 "reassignment": "/panel/maquinarias/", "manual": "/panel/notificaciones/",
                 "advertiser": "/panel/", "unknown": "/panel/"}
        for kind, path in paths.items():
            with self.subTest(kind=kind):
                notice = self.notice(kind, "Mensaje aprobado por el equipo, conservado literalmente.")
                context = notification_context(notice)
                self.assertEqual(context["cta_url"], "https://portal.example.com" + path)
                self.assertEqual(context["paragraphs"], [notice.body])
                self.assertNotIn("publicada", context["preheader"])
                if kind == "manual":
                    self.assertEqual(context["cta_label"], "Ver mi notificación")

    def test_deleted_or_reassigned_machine_does_not_get_an_inaccessible_detail_button(self):
        for deleted in (True, False):
            with self.subTest(deleted=deleted):
                self.machine.deleted_at = timezone.now() if deleted else None
                if not deleted:
                    self.machine.owner = User.objects.create_user(email="new-owner@example.invalid")
                self.machine.save()
                for kind, path in (("reply", "/panel/mensajes/"), ("reminder", "/panel/maquinarias/")):
                    context = notification_context(self.notice(kind))
                    self.assertEqual(context["cta_url"], "https://portal.example.com" + path)

    def test_access_links_are_stable_private_and_bound_to_their_recipient(self):
        notice = activation_email(self.user, "recovery")
        first = build_notification_email(notice)
        second = build_notification_email(notice)
        context = notification_context(notice)
        self.assertIn(context["cta_url"], first.body)
        self.assertEqual(first.extra_headers["Message-ID"], second.extra_headers["Message-ID"])
        self.assertEqual(first.body, second.body)
        self.assertNotIn(context["cta_url"], context["preheader"])
        self.assertNotIn(context["cta_url"], first.subject)
        self.assertNotIn(context["cta_url"], "\n".join(context["paragraphs"]))
        self.assertEqual(EmailMarkup(first.alternatives[0].content).images, ["cid:imc-logo"])
        other = User.objects.create_user(email="other-recipient@example.com")
        notice.user = other
        with self.assertRaises(NotificationNotSendable):
            build_notification_email(notice)

    def test_access_links_reject_host_credentials_query_fragment_and_malformed_routes(self):
        notice = activation_email(self.user, "recovery")
        original = notice.body
        url = notification_context(notice)["cta_url"]
        forged = [url.replace("portal.example.com", "evil.example.com"),
                  url.replace("https://", "https://evil@"),
                  url + "?next=https://evil.example", url + "#fragment",
                  url.replace("/activar/", "/other/"),
                  url.replace("https://", "javascript:"),
                  url + "\nhttps://evil.example/"]
        for value in forged:
            with self.subTest(case=forged.index(value)):
                notice.body = original.replace(url, value)
                with self.assertRaises(NotificationNotSendable) as error:
                    build_notification_email(notice)
                self.assertNotIn(value, str(error.exception))

    def test_expired_or_consumed_access_mail_is_terminal_without_smtp_or_a_new_token(self):
        for consumed in (False, True):
            with self.subTest(consumed=consumed):
                notice = activation_email(self.user, "recovery")
                original = notice.body
                if consumed:
                    self.user.set_password("Changed-only-in-local-tests-940!")
                    self.user.save()
                else:
                    Notification.objects.filter(pk=notice.pk).update(created_at=timezone.now() - timedelta(hours=2))
                with patch("django.core.mail.message.EmailMultiAlternatives.send") as send:
                    self.assertEqual(process_notifications(), 0)
                send.assert_not_called()
                notice.refresh_from_db()
                self.assertEqual(notice.status, "failed")
                self.assertEqual(notice.attempts, 1)
                self.assertEqual(notice.body, original)
                self.assertNotIn("/activar/", notice.error)

    def test_registration_verification_remains_valid_after_initial_login(self):
        response = self.client.post("/registro/", {"first_name": "Registro de prueba", "last_name": "Cuenta", "email": "new@example.invalid",
            "phone": "+525512345678", "contact_preference": "email", "password1": "New-test-password-481!",
            "password2": "New-test-password-481!", "terms": "on"})
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="new@example.invalid")
        self.assertIsNotNone(user.last_login)
        notice = Notification.objects.get(user=user, kind="verify")
        context = notification_context(notice)
        token = urlsplit(context["cta_url"]).path.rstrip("/").split("/")[-1]
        self.assertTrue(default_token_generator.check_token(user, token))
        self.assertContains(self.client.get(urlsplit(context["cta_url"]).path), "Establece tu contraseña")
        self.assertEqual(notice.status, "pending")

    def test_retention_redacts_the_only_persistent_access_url_copy(self):
        notice = activation_email(self.user, "recovery")
        url = notification_context(notice)["cta_url"]
        Notification.objects.filter(pk=notice.pk).update(created_at=timezone.now() - timedelta(hours=2))
        call_command("retention", apply=True, stdout=StringIO())
        notice.refresh_from_db()
        self.assertNotIn(url, notice.body)
        self.assertEqual(notice.status, "failed")
        with self.assertRaises(NotificationNotSendable):
            build_notification_email(notice)

    def test_reply_to_is_single_configured_mailbox_and_never_taken_from_user_content(self):
        notice = self.notice(body="Reply-To: malicious@example.com")
        self.assertEqual(build_notification_email(notice).reply_to, [])
        with override_settings(EMAIL_REPLY_TO="Equipo IMC <soporte@example.com>"):
            self.assertEqual(build_notification_email(notice).reply_to, ["soporte@example.com"])
        for bad in ("soporte@example.com\r\nBcc: evil@example.com", "not-an-email", "one@example.com,two@example.com"):
            with self.subTest(invalid_setting=True), override_settings(EMAIL_REPLY_TO=bad), self.assertRaises(NotificationNotSendable):
                build_notification_email(notice)
