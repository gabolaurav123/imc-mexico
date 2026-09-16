"""Real admin POSTs and the private outbox, using only the isolated test database."""
import uuid
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from portal.communications import queue_manual_notification, save_staff_message
from portal.models import AuditEvent, Machine, Message, Notification, User


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False,
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AdministrativeCommunicationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(email="support@example.invalid", is_staff=True)
        self.owner = User.objects.create_user(email="recipient@example.invalid", first_name="Private recipient")
        self.machine = Machine.objects.create(owner=self.owner, title="Private unsent draft")
        self.grant("operate_platform", "view_machine", "add_message", "view_message", "add_notification",
                   "view_notification", "view_user")
        self.login()

    def grant(self, *names):
        self.staff.user_permissions.set(Permission.objects.filter(content_type__app_label="portal", codename__in=names))
        for cache in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            self.staff.__dict__.pop(cache, None)

    def login(self, verified=True, client=None, user=None):
        client = client or self.client
        user = user or self.staff
        client.logout()
        client.force_login(user)
        if verified:
            device, _ = TOTPDevice.objects.get_or_create(user=user, name="test-device", confirmed=True)
            session = client.session
            session[DEVICE_ID_SESSION_KEY] = device.persistent_id
            session.save()
            user.is_verified = lambda: True
        else:
            user.is_verified = lambda: False

    def form_payload(self, client=None, **updates):
        response = (client or self.client).get("/operaciones/notificaciones/nueva/")
        self.assertEqual(response.status_code, 200)
        payload = {"recipient": self.owner.pk, "subject": "Información sobre tu maquinaria",
                   "body": "Por favor, confirma el accesorio visible.",
                   "request_token": response.context["form"].initial["request_token"]}
        payload.update(updates)
        return payload

    def test_individual_post_queues_both_channels_and_duplicate_post_is_idempotent(self):
        data = self.form_payload()
        with patch("portal.emailing.send_notification_email") as send:
            response = self.client.post("/operaciones/notificaciones/nueva/", data)
            repeated = self.client.post("/operaciones/notificaciones/nueva/", data)
        send.assert_not_called()
        self.assertEqual((response.status_code, repeated.status_code), (302, 302))
        notices = Notification.objects.filter(kind="manual", user=self.owner)
        self.assertEqual(notices.count(), 2)
        self.assertEqual(notices.get(channel="email").status, "pending")
        self.assertEqual(notices.get(channel="in_app").status, "sent")
        self.assertTrue(all(item.machine_id is None for item in notices))
        event = AuditEvent.objects.get(action="notification.manual_queued")
        self.assertEqual(event.actor, self.staff)
        self.assertNotIn(data["body"], str(event.metadata))
        self.login(user=self.owner)
        inbox=self.client.get('/panel/notificaciones/')
        self.assertContains(inbox,data['subject'])
        self.assertContains(inbox,data['body'])
        self.assertEqual(inbox['Cache-Control'],'private, no-store')

    def test_composer_requires_recipient_permission_mfa_and_csrf(self):
        self.grant("operate_platform", "add_notification")
        response = self.client.get("/operaciones/notificaciones/nueva/")
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, self.owner.email, status_code=403)
        self.grant("operate_platform", "add_notification", "view_user")
        self.login(verified=False)
        response = self.client.get("/operaciones/notificaciones/nueva/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/panel/seguridad/"))
        csrf_client = Client(enforce_csrf_checks=True)
        self.login(client=csrf_client)
        data = self.form_payload(client=csrf_client)
        self.assertEqual(csrf_client.post("/operaciones/notificaciones/nueva/", data).status_code, 403)
        self.assertFalse(Notification.objects.exists())

    def test_composer_rejects_inactive_recipient_header_injection_and_forged_token(self):
        original = self.form_payload()
        for changes in ({"subject": "Hello\nBcc: forged@example.invalid"},
                        {"request_token": "forged"}, {"body": " "}):
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post("/operaciones/notificaciones/nueva/", {**original, **changes}).status_code, 200)
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self.assertEqual(self.client.post("/operaciones/notificaciones/nueva/", original).status_code, 200)
        self.assertFalse(Notification.objects.exists())

    def test_admin_message_to_draft_notifies_owner_and_internal_note_does_not(self):
        for internal in (False, True):
            data = {"machine": str(self.machine.pk), "body": "Private <instruction> for recipient", "_save": "Guardar"}
            if internal:
                data["internal"] = "on"
            response = self.client.post("/admin/portal/message/add/", data)
            self.assertEqual(response.status_code, 302)
        self.assertEqual(Message.objects.filter(machine=self.machine).count(), 2)
        self.assertEqual(Notification.objects.filter(user=self.owner, kind="reply").count(), 2)
        self.assertEqual(Notification.objects.get(channel="email").status, "pending")
        self.assertEqual(AuditEvent.objects.filter(action__in=["message.reply", "message.internal"]).count(), 2)
        self.assertFalse(self.machine.submissions.exists())
        response = self.client.get("/operaciones/")
        self.assertContains(response, "Private &lt;instruction&gt; for recipient")
        self.assertNotContains(response, "Private <instruction> for recipient")

    def test_message_permission_does_not_grant_machine_selection_and_history_is_immutable(self):
        self.grant("operate_platform", "add_message", "view_message")
        self.assertEqual(self.client.get("/admin/portal/message/add/").status_code, 403)
        self.grant("operate_platform", "view_machine", "add_message", "change_message", "view_message")
        message = Message(machine=self.machine, body="Original message")
        save_staff_message(message, self.staff)
        self.client.post(f"/admin/portal/message/{message.pk}/change/", {"body": "Changed", "_save": "Guardar"})
        message.refresh_from_db()
        self.assertEqual(message.body, "Original message")
        self.assertEqual(Notification.objects.count(), 2)

    def test_services_enforce_permissions_and_mfa_without_relying_on_form(self):
        self.staff.is_verified = lambda: False
        with self.assertRaises(PermissionDenied):
            queue_manual_notification(actor=self.staff, recipient=self.owner, subject="Subject", body="Message", request_id=uuid.uuid4().hex)
        with self.assertRaises(PermissionDenied):
            save_staff_message(Message(machine=self.machine, body="Message"), self.staff)
        self.staff.is_verified = lambda: True
        with self.assertRaises(ValidationError):
            queue_manual_notification(actor=self.staff, recipient=self.owner, subject="\nInjected\nheader", body="Message", request_id=uuid.uuid4().hex)
        self.machine.deleted_at=timezone.now()
        self.machine.save(update_fields=['deleted_at'])
        with self.assertRaises(PermissionDenied):
            save_staff_message(Message(machine=self.machine,body='Already selected before deletion'),self.staff)
        self.assertFalse(Notification.objects.exists())

    def test_operations_summaries_exclude_auth_secrets_and_obey_each_permission(self):
        Notification.objects.create(user=self.owner, kind="recovery", subject="AUTH-SECRET-SUBJECT", body="AUTH-SECRET-TOKEN", channel="email")
        regular = Notification.objects.create(user=self.owner, kind="manual", subject="PRIVATE-SUPPORT-SUBJECT", body="PRIVATE-MESSAGE-BODY", channel="email")
        Message.objects.create(machine=self.machine, sender=self.owner, body="PRIVATE-CONVERSATION")
        self.owner.last_login = timezone.now()
        self.owner.save(update_fields=["last_login"])
        response = self.client.get("/operaciones/")
        self.assertContains(response, "Fichas y borradores recientes")
        self.assertContains(response, self.machine.title)
        self.assertContains(response, "PRIVATE-CONVERSATION")
        self.assertContains(response, regular.subject)
        self.assertNotContains(response, "AUTH-SECRET")
        self.assertNotContains(response, regular.body)
        self.assertEqual(response.context["counts"]["pending_emails"], 1)
        self.grant("operate_platform")
        response = self.client.get("/operaciones/")
        for name in ("recent_users", "recent_machines", "recent_messages", "recent_notifications"):
            self.assertEqual(list(response.context[name]), [])
        for text in (self.owner.email, self.machine.title, "PRIVATE-CONVERSATION", regular.subject):
            self.assertNotContains(response, text)

    def test_inactive_external_message_rejected_but_internal_note_allowed(self):
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        response = self.client.post("/admin/portal/message/add/", {"machine": self.machine.pk, "body": "Please respond", "_save": "Guardar"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Message.objects.exists())
        response = self.client.post("/admin/portal/message/add/", {"machine": self.machine.pk, "body": "Internal follow-up", "internal": "on", "_save": "Guardar"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Message.objects.get().internal)
        self.assertFalse(Notification.objects.exists())

    def test_inbox_is_owner_only_excludes_auth_and_email_and_paginates(self):
        Notification.objects.create(user=self.staff,kind='manual',subject='OTHER-USER-SECRET',body='Private',channel='in_app')
        Notification.objects.create(user=self.owner,kind='recovery',subject='AUTH-TOKEN-SECRET',body='Token',channel='in_app')
        Notification.objects.create(user=self.owner,kind='manual',subject='EMAIL-ONLY-SECRET',body='Private',channel='email')
        for index in range(21):
            Notification.objects.create(user=self.owner,kind='manual',subject=f'Own notice {index}',body='<b>Plain content</b>',channel='in_app',status='sent')
        self.login(user=self.owner)
        response=self.client.get('/panel/notificaciones/',{'user':self.staff.pk})
        self.assertEqual(len(response.context['notifications']),20)
        for text in ('OTHER-USER-SECRET','AUTH-TOKEN-SECRET','EMAIL-ONLY-SECRET'):
            self.assertNotContains(response,text)
        self.assertContains(response,'&lt;b&gt;Plain content&lt;/b&gt;')
        self.assertNotContains(response,'<b>Plain content</b>')
        response=self.client.get('/panel/notificaciones/?page=2')
        self.assertEqual(len(response.context['notifications']),1)
        self.client.logout()
        self.assertEqual(self.client.get('/panel/notificaciones/').status_code,302)

    def test_empty_inbox_has_no_foreign_account_information(self):
        Notification.objects.create(user=self.staff,kind='manual',subject='OTHER-USER-SECRET',body='Private',channel='in_app')
        self.login(user=self.owner)
        response=self.client.get('/panel/notificaciones/')
        self.assertEqual(response.status_code,200)
        self.assertEqual(list(response.context['notifications']),[])
        self.assertNotContains(response,'OTHER-USER-SECRET')
