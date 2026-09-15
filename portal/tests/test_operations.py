from datetime import timedelta
from io import StringIO
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.management import call_command
from django.test import RequestFactory,TestCase,override_settings
from django.utils import timezone

from portal.admin import AnalyticsAdmin
from portal.models import AnalyticsEvent,Asset,Machine,Notification,NotificationTemplate,PlatformSettings,RateLimit,User
from portal.security import RedactingFormatter
from portal.services import find_possible_duplicates,send_machine_reminder,submit_machine


class OperationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner=User.objects.create_user(email="ops-owner@example.com",password=None)
        cls.admin=User.objects.create_superuser(email="ops-admin@example.com",password=None)
        cls.reader=User.objects.create_user(email="ops-reader@example.com",password=None,is_staff=True)
        cls.reader.user_permissions.add(Permission.objects.get(content_type__app_label="portal",codename="view_machine"))

    def setUp(self):
        self.machine=Machine.objects.create(owner=self.owner,title="Equipo",data={"brand":"Marca","model":"Modelo","location":"Ubicación","serial":"SERIE123"})

    def test_duplicate_suggestions_require_staff_permission_and_never_merge(self):
        matched=Machine.objects.create(owner=self.owner,title="Posible",data={"brand":"marca","model":"modelo"})
        ignored=Machine.objects.create(owner=self.owner,title="Distinto",data={"brand":"Otra","model":"Otra"})
        self.assertEqual([item.pk for item in find_possible_duplicates(self.machine,self.reader)],[matched.pk])
        with self.assertRaises(PermissionDenied):find_possible_duplicates(self.machine,self.owner)
        self.assertEqual(Machine.objects.count(),3)
        self.assertTrue(Machine.objects.filter(pk=ignored.pk).exists())

    def test_empty_unknown_identifiers_do_not_match_other_blank_machines(self):
        one=Machine.objects.create(owner=self.owner,data={})
        Machine.objects.create(owner=self.owner,data={"serial":None})
        self.assertFalse(find_possible_duplicates(one,self.admin))

    def test_editable_notification_template_uses_safe_allowed_placeholders(self):
        NotificationTemplate.objects.create(key="reminder",subject="$folio: completar ficha",body="Hola $name. $reason\n$title\n$portal_url")
        send_machine_reminder(self.machine,self.admin,"Agrega ubicación general.")
        notice=Notification.objects.get(kind="reminder",channel="email")
        self.assertIn(self.machine.folio,notice.subject)
        self.assertIn("Agrega ubicación general.",notice.body)
        self.assertEqual(notice.status,"pending")
        with self.assertRaises(PermissionDenied):send_machine_reminder(self.machine,self.owner,"No autorizado")

    def test_notification_template_rejects_secret_or_expression_placeholders(self):
        for body in ("$password", "${user.password}", "$unknown", "Una variable incompleta $"):
            template=NotificationTemplate(key="reminder",subject="Recordatorio",body=body)
            with self.assertRaises(ValidationError):template.full_clean()

    def test_invalid_template_cannot_prevent_workflow_notifications(self):
        NotificationTemplate.objects.create(key="submission",subject="Invalid $secret",body="Mensaje")
        Asset.objects.create(machine=self.machine,kind="image",purpose="general",processing_status="ready",original="private.jpg",mime_type="image/jpeg",sha256="a"*64)
        submission=submit_machine(self.machine,self.owner,True)
        self.assertEqual(submission.status,"submitted")
        self.assertTrue(Notification.objects.filter(kind="submission",channel="email").exists())

    def test_analytics_export_requires_explicit_permission_and_escapes_csv_formulas(self):
        event=AnalyticsEvent.objects.create(event="submission_sent",user=self.owner,machine=self.machine,source="=HYPERLINK(1)",campaign="@unsafe",device="mobile")
        request=RequestFactory().post("/admin/portal/analyticsevent/")
        request.user=self.reader
        model_admin=AnalyticsAdmin(AnalyticsEvent,AdminSite())
        with self.assertRaises(PermissionDenied):model_admin.export_events(request,AnalyticsEvent.objects.all())
        self.reader.user_permissions.add(Permission.objects.get(content_type__app_label="portal",codename="export_analytics"))
        request.user=User.objects.get(pk=self.reader.pk)
        response=model_admin.export_events(request,AnalyticsEvent.objects.all())
        self.assertEqual(response.status_code,200)
        self.assertIn("'=HYPERLINK(1)",response.content.decode())
        self.assertIn("'@unsafe",response.content.decode())
        self.assertNotIn(self.owner.email,response.content.decode())
        self.assertIn("registrado",response.content.decode())

    def test_retention_is_read_only_by_default_and_never_deletes_media(self):
        platform=PlatformSettings.objects.create(retention_days=30)
        past=timezone.now()-timedelta(days=40)
        Session.objects.create(session_key="expired",session_data="",expire_date=past)
        RateLimit.objects.create(key="old-rate",window_start=past)
        event=AnalyticsEvent.objects.create(event="old")
        AnalyticsEvent.objects.filter(pk=event.pk).update(created_at=past)
        token_notice=Notification.objects.create(user=self.owner,kind="recovery",subject="Recuperación",body="expired token",channel="email")
        Notification.objects.filter(pk=token_notice.pk).update(created_at=past)
        with TemporaryDirectory() as directory,override_settings(MEDIA_ROOT=directory,PRIVATE_S3_BUCKET=""):
            path=Path(directory)/"unreferenced.jpg";path.write_bytes(b"kept")
            report=StringIO();call_command("retention","--inspect-media",stdout=report)
            self.assertIn('"mode": "report_only"',report.getvalue())
            self.assertTrue(Session.objects.filter(pk="expired").exists())
            self.assertTrue(AnalyticsEvent.objects.filter(pk=event.pk).exists())
            call_command("retention","--apply","--inspect-media",stdout=StringIO())
            self.assertFalse(Session.objects.filter(pk="expired").exists())
            self.assertFalse(RateLimit.objects.filter(key="old-rate").exists())
            self.assertFalse(AnalyticsEvent.objects.filter(pk=event.pk).exists())
            self.assertTrue(path.exists())
            self.assertTrue(Machine.objects.filter(pk=self.machine.pk).exists())
            token_notice.refresh_from_db()
            self.assertEqual(token_notice.status,"failed")
            self.assertNotIn("expired token",token_notice.body)

    def test_log_formatter_redacts_activation_url_and_exception_tokens(self):
        formatter=RedactingFormatter("%(levelname)s %(message)s")
        record=logging.LogRecord("django.request",logging.ERROR,"test",1,"Not Found: /activar/ABC/PRIVATE-TOKEN/",(),None)
        text=formatter.format(record)
        self.assertNotIn("PRIVATE-TOKEN",text)
        self.assertNotIn("ABC",text)
        try:raise ValueError("https://example.com/activar/XYZ/OTHER-PRIVATE/?token=QUERY-SECRET")
        except ValueError:
            import sys
            record=logging.LogRecord("test",logging.ERROR,"test",2,"Exception",(),sys.exc_info())
        text=formatter.format(record)
        self.assertNotIn("OTHER-PRIVATE",text)
        self.assertNotIn("QUERY-SECRET",text)
