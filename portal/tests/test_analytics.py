import json
from io import StringIO
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import DatabaseError
from django.test import Client,RequestFactory,TestCase,override_settings
from django.utils import timezone

from portal.analytics import (CONSENT_COOKIE,SESSION_COOKIE,capture_context,page_category,
    record_event,record_job_completion,safe_slug,session_hash)
from portal.models import AnalysisJob,AnalyticsEvent,Asset,Consent,Lead,Machine,PlatformSettings,User


@override_settings(STAFF_MFA_REQUIRED=False,SECURE_SSL_REDIRECT=False,
    STORAGES={"default":{"BACKEND":"portal.storage.PrivateStorage"},"staticfiles":{"BACKEND":"django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AnalyticsPrivacyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner=User.objects.create_user(email="analytics-owner@example.com",password=None)
        cls.staff=User.objects.create_user(email="analytics-staff@example.com",password=None,is_staff=True)
        cls.tester=User.objects.create_user(email="analytics@example.invalid",password=None)

    def setUp(self):
        self.platform=PlatformSettings.objects.create()
        self.machine=Machine.objects.create(owner=self.owner,title="Equipo privado",data={"location":"Querétaro"})
        self.photo=Asset.objects.create(machine=self.machine,kind="image",purpose="general",processing_status="ready",original="private.jpg",mime_type="image/jpeg",sha256="a"*64)

    def enable(self,require_consent=True):
        self.platform.analytics_enabled=True
        self.platform.analytics_require_consent=require_consent
        self.platform.save()

    def preference(self,value,client=None,**kwargs):
        return (client or self.client).post("/preferencias/analitica/",json.dumps({"consent":value}),content_type="application/json",**kwargs)

    def context(self,client=None,page="analysis"):
        request=RequestFactory().get("/?utm_source=search&utm_campaign=launch",HTTP_USER_AGENT="Mobile Example")
        request.user=self.owner
        request.COOKIES={name:cookie.value for name,cookie in (client or self.client).cookies.items()}
        return capture_context(request,page=page)

    def job(self,context,status="completed"):
        return AnalysisJob.objects.create(machine=self.machine,requested_by=self.owner,revision=1,fingerprint="b"*64,status=status,analytics_context=context)

    def test_disabled_by_default_has_no_events_or_analytics_cookies_or_prompt(self):
        response=self.client.get("/?utm_source=search&utm_campaign=launch")
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'id="analytics-preferences"')
        self.assertFalse(AnalyticsEvent.objects.exists())
        self.assertNotIn(SESSION_COOKIE,response.cookies)
        self.assertNotIn(CONSENT_COOKIE,response.cookies)
        self.assertEqual(self.preference(True).status_code,400)
        self.client.force_login(self.owner)
        self.client.post("/api/maquinarias/",data="{}",content_type="application/json")
        self.assertFalse(AnalyticsEvent.objects.exists())

    def test_required_consent_waits_for_explicit_choice_and_denial_stops(self):
        self.enable()
        response=self.client.get("/")
        self.assertContains(response,'id="analytics-preferences"')
        self.assertFalse(AnalyticsEvent.objects.exists())
        self.assertNotIn(SESSION_COOKIE,response.cookies)
        self.assertEqual(self.preference(False).status_code,200)
        self.client.get("/")
        self.assertFalse(AnalyticsEvent.objects.exists())

    def test_preference_requires_csrf_post_and_boolean_exact_payload(self):
        self.enable()
        secure=Client(enforce_csrf_checks=True)
        self.assertEqual(self.preference(True,secure).status_code,403)
        secure.get("/")
        self.assertIn("csrftoken",secure.cookies)
        response=self.preference(True,secure,HTTP_X_CSRFTOKEN=secure.cookies["csrftoken"].value)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.cookies[CONSENT_COOKIE]["httponly"])
        self.assertEqual(response.cookies[CONSENT_COOKIE]["samesite"],"Lax")
        self.assertEqual(self.client.get("/preferencias/analitica/").status_code,405)
        for payload in ({"consent":"true"},{"consent":1},{"consent":True,"email":"private@example.com"},[],{}):
            self.assertEqual(self.client.post("/preferencias/analitica/",json.dumps(payload),content_type="application/json").status_code,400)
        self.assertFalse(AnalyticsEvent.objects.exists())

    def test_aggregate_mode_has_no_identifiers_or_analytics_cookies(self):
        self.enable(require_consent=False)
        self.client.force_login(self.owner)
        response=self.client.get("/?utm_source=SEARCH&utm_campaign=Launch-2026",HTTP_USER_AGENT="Mobile Example",REMOTE_ADDR="198.51.100.9",HTTP_REFERER="https://example.com/customer/private-id")
        event=AnalyticsEvent.objects.get()
        self.assertEqual((event.source,event.campaign,event.device,event.page),("search","launch-2026","mobile","home"))
        self.assertEqual(event.actor_type,"registered")
        self.assertEqual(event.session_hash,"")
        self.assertIsNone(event.user_id)
        self.assertIsNone(event.machine_id)
        self.assertNotIn(SESSION_COOKIE,response.cookies)
        self.assertNotIn(CONSENT_COOKIE,response.cookies)
        self.preference(False)
        self.client.get("/")
        self.assertEqual(AnalyticsEvent.objects.count(),1)

    def test_anonymous_visits_never_create_leads_or_user_records(self):
        self.enable()
        count=User.objects.count()
        self.preference(True)
        response=self.client.get("/?utm_source=search&utm_campaign=launch",HTTP_USER_AGENT="iPad")
        event=AnalyticsEvent.objects.get()
        self.assertEqual((event.actor_type,event.device),("anonymous","tablet"))
        self.assertRegex(event.session_hash,r"^[a-f0-9]{64}$")
        self.assertEqual(User.objects.count(),count)
        self.assertFalse(Lead.objects.exists())
        self.assertFalse(Consent.objects.exists())
        self.assertIn(SESSION_COOKIE,response.cookies)
        self.assertIsNone(event.user_id)
        self.assertIsNone(event.machine_id)

    def test_sensitive_query_referrer_user_agent_and_path_identifiers_are_not_stored(self):
        self.enable()
        self.preference(True)
        self.client.force_login(self.owner)
        self.client.get(f"/panel/maquinarias/{self.machine.pk}/?utm_source=private%40example.com&utm_campaign=https://private.example/customer/secret&token=hidden",HTTP_USER_AGENT="Mobile ExactDeviceIdentifier",REMOTE_ADDR="198.51.100.9",HTTP_REFERER="https://private.example/secret-customer")
        event=AnalyticsEvent.objects.get()
        self.assertEqual((event.source,event.campaign,event.page),("direct","","wizard"))
        stored=json.dumps(list(AnalyticsEvent.objects.values()),default=str)
        for secret in ("private@example.com","198.51.100.9","ExactDeviceIdentifier","secret-customer","hidden",str(self.machine.pk),self.owner.email):
            self.assertNotIn(secret,stored)
        self.assertIsNone(event.user_id)
        self.assertIsNone(event.machine_id)
        for source in ("+525512345678","525512345678","<script>","x"*61,str(self.machine.pk),"169254169254"):
            self.assertEqual(safe_slug(source),"")

    def test_session_attribution_is_ephemeral_browser_specific_and_daily_salted(self):
        self.enable()
        self.preference(True)
        self.client.get("/?utm_source=search&utm_campaign=launch")
        first=AnalyticsEvent.objects.latest("pk")
        self.client.get("/como-funciona/?utm_source=other")
        second=AnalyticsEvent.objects.latest("pk")
        self.assertEqual(first.session_hash,second.session_hash)
        self.assertEqual(second.source,"search")
        other=Client();self.preference(True,other);other.get("/")
        self.assertNotEqual(first.session_hash,AnalyticsEvent.objects.latest("pk").session_hash)
        now=timezone.now()
        self.assertNotEqual(session_hash("nonce",now),session_hash("nonce",now+timedelta(days=1)))
        with patch("portal.analytics.timezone.now",return_value=now+timedelta(minutes=31)):
            self.client.get("/?utm_source=other")
        expired=AnalyticsEvent.objects.latest("pk")
        self.assertNotEqual(first.session_hash,expired.session_hash)
        self.assertEqual(expired.source,"other")

    def test_staff_test_and_registered_are_separate_without_identity(self):
        self.enable(require_consent=False)
        for user,expected in ((self.owner,"registered"),(self.staff,"staff"),(self.tester,"test")):
            self.client.force_login(user)
            self.client.get("/")
            event=AnalyticsEvent.objects.latest("pk")
            self.assertEqual(event.actor_type,expected)
            self.assertEqual(event.is_test,expected=="test")
            self.assertIsNone(event.user_id)
            self.assertIsNone(event.machine_id)

    def test_revocation_clears_current_hash_and_queued_context_and_records_separate_consent(self):
        self.enable()
        self.client.force_login(self.owner)
        self.preference(True)
        self.client.get("/")
        job=self.job(self.context(),status="queued")
        event=AnalyticsEvent.objects.get()
        self.assertTrue(event.session_hash)
        self.preference(False)
        event.refresh_from_db();job.refresh_from_db()
        self.assertEqual(event.session_hash,"")
        self.assertEqual(job.analytics_context,{})
        self.assertEqual(self.client.cookies[SESSION_COOKIE].value,"")
        self.assertEqual(list(Consent.objects.filter(kind="analytics").order_by("pk").values_list("granted",flat=True)),[True,False])
        self.assertFalse(Consent.objects.filter(kind="marketing").exists())
        self.owner.refresh_from_db();self.assertFalse(self.owner.marketing_consent)
        self.client.get("/")
        self.assertEqual(AnalyticsEvent.objects.count(),1)

    def test_tampered_cookie_does_not_authorize_tracking(self):
        self.enable()
        self.client.cookies[CONSENT_COOKIE]="granted"
        self.client.get("/")
        self.assertFalse(AnalyticsEvent.objects.exists())

    def test_aggregate_opt_out_stops_pending_analysis_without_cookie_identifier(self):
        self.enable(require_consent=False)
        self.client.force_login(self.owner)
        job=self.job(self.context(),status='running')
        self.assertFalse(job.analytics_context['session_hash'])
        self.assertEqual(self.preference(False).status_code,200)
        job.refresh_from_db();self.assertEqual(job.analytics_context,{})
        job.status='completed';job.save(update_fields=['status'])
        record_job_completion(job)
        self.assertFalse(AnalyticsEvent.objects.exists())

    def test_disabling_global_switch_stops_and_removes_old_browser_cookies(self):
        self.enable();self.preference(True);self.client.get("/")
        self.platform.analytics_enabled=False;self.platform.save()
        response=self.client.get("/")
        self.assertEqual(AnalyticsEvent.objects.count(),1)
        self.assertEqual(response.cookies[SESSION_COOKIE]["max-age"],0)
        self.assertEqual(response.cookies[CONSENT_COOKIE]["max-age"],0)

    def test_sensitive_routes_and_uuid_are_categorized_or_excluded(self):
        for path in ("/activar/private/token/","/recuperar-acceso/","/panel/seguridad/","/archivos/secret/","/api/analisis/secret/"):
            self.assertEqual(page_category(path),"")
        self.assertEqual(page_category(f"/ficha/{self.machine.pk}/"),"shared_sheet")
        self.enable();self.preference(True)
        self.client.get("/activar/private/token/")
        self.client.get("/recuperar-acceso/")
        self.assertFalse(AnalyticsEvent.objects.exists())

    def test_async_completion_counts_once_then_discards_context(self):
        self.enable();self.preference(True);self.client.get("/")
        job=self.job(self.context())
        record_job_completion(job);record_job_completion(job)
        event=AnalyticsEvent.objects.get(event="analysis_completed")
        self.assertEqual((event.page,event.actor_type),("analysis","registered"))
        self.assertIsNone(event.user_id);self.assertIsNone(event.machine_id)
        job.refresh_from_db();self.assertEqual(job.analytics_context,{"_recorded":True})

    def test_async_completion_ignores_expired_disabled_and_empty_context(self):
        self.enable();self.preference(True);self.client.get("/")
        context=self.context();context["_expires_at"]=timezone.now().timestamp()-1
        job=self.job(context)
        record_job_completion(job)
        job.analytics_context=self.context();job.save(update_fields=["analytics_context"])
        self.platform.analytics_enabled=False;self.platform.save()
        record_job_completion(job)
        job.analytics_context={};job.save(update_fields=["analytics_context"])
        record_job_completion(job)
        self.assertFalse(AnalyticsEvent.objects.filter(event="analysis_completed").exists())

    def test_metrics_database_failure_does_not_break_primary_request(self):
        self.enable(require_consent=False)
        request=RequestFactory().get("/");request.user=AnonymousUser()
        with patch("portal.analytics._write_event",side_effect=DatabaseError("optional storage unavailable")):
            self.assertIsNone(record_event(request,"page_view"))
        self.assertTrue(Machine.objects.filter(pk=self.machine.pk).exists())

    def test_registration_funnel_needs_choice_and_does_not_identify_new_account(self):
        self.enable();self.platform.registration_open=True;self.platform.legal_validated=True;self.platform.save()
        self.preference(True)
        self.client.get("/registro/")
        self.assertEqual(AnalyticsEvent.objects.filter(event="register_started").count(),1)
        response=self.client.post("/registro/",{"first_name":"Ensayo","email":"new-account@example.com","phone":"+525512345678","contact_preference":"email","password1":"A-strong-test-password-937!","password2":"A-strong-test-password-937!","terms":"on"})
        self.assertEqual(response.status_code,302)
        user=User.objects.get(email="new-account@example.com")
        self.assertTrue(Consent.objects.filter(user=user,kind="analytics",granted=True).exists())
        event=AnalyticsEvent.objects.get(event="register_completed")
        self.assertEqual(event.actor_type,"registered");self.assertIsNone(event.user_id)
        self.assertFalse(user.marketing_consent)

    def test_upload_and_submission_funnel_preserves_privacy(self):
        self.enable();self.client.force_login(self.owner);self.preference(True)
        with patch("portal.processing.ingest_asset",return_value=self.photo):
            response=self.client.post(f"/api/maquinarias/{self.machine.pk}/archivos/",{"file":SimpleUploadedFile("test.jpg",b"test",content_type="image/jpeg")})
        self.assertEqual(response.status_code,201)
        self.assertEqual(AnalyticsEvent.objects.filter(event="upload_started").count(),1)
        response=self.client.post(f"/api/maquinarias/{self.machine.pk}/enviar/",json.dumps({"advertise_consent":True}),content_type="application/json")
        self.assertEqual(response.status_code,200)
        self.assertEqual(AnalyticsEvent.objects.filter(event="submission_sent").count(),1)
        self.assertFalse(AnalyticsEvent.objects.exclude(user_id=None).exists())
        self.assertFalse(AnalyticsEvent.objects.exclude(machine_id=None).exists())

    def test_retention_clears_old_session_identifiers_but_keeps_aggregate_events(self):
        self.enable();self.preference(True);self.client.get('/')
        event=AnalyticsEvent.objects.get()
        AnalyticsEvent.objects.filter(pk=event.pk).update(created_at=timezone.now()-timedelta(minutes=31))
        context=self.context();context['_expires_at']=timezone.now().timestamp()-1
        job=self.job(context,status='queued')
        call_command('retention',stdout=StringIO())
        event.refresh_from_db();job.refresh_from_db()
        self.assertTrue(event.session_hash);self.assertTrue(job.analytics_context)
        call_command('retention','--apply',stdout=StringIO())
        event.refresh_from_db();job.refresh_from_db()
        self.assertEqual(event.session_hash,'');self.assertEqual(job.analytics_context,{})
        self.assertEqual(event.event,'page_view')
