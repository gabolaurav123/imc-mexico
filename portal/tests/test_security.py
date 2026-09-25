import json
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.contrib.auth.tokens import default_token_generator
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from PIL import Image

from portal.models import (AnalysisJob, Asset, AuditEvent, Machine, Message, Notification,
                           Publication, Submission, User, PlatformSettings, Lead)
from portal.services import (record_local_duplicate_review, review_submission, set_advertiser_status,
                             set_publication, submit_machine)
from portal.views import safe_public_data, sheet_context


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False,
    STORAGES={"default":{"BACKEND":"portal.storage.PrivateStorage"},"staticfiles":{"BACKEND":"django.contrib.staticfiles.storage.StaticFilesStorage"}})
class WebSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner=User.objects.create_user(email="owner@example.com",password="Owner-password-long123")
        cls.other=User.objects.create_user(email="other@example.com",password="Other-password-long123")
        cls.admin=User.objects.create_superuser(email="admin@example.com",password="Admin-password-long123")
        cls.operator=User.objects.create_user(email="commercial@example.com",password="Commercial-long123",is_staff=True)
        cls.operator.user_permissions.add(*Permission.objects.filter(content_type__app_label="portal",codename__in=["operate_platform","view_machine"]))

    def setUp(self):
        self.directory=TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.media=override_settings(MEDIA_ROOT=self.directory.name,PRIVATE_S3_BUCKET="")
        self.media.enable()
        self.addCleanup(self.media.disable)
        self.machine=Machine.objects.create(owner=self.owner,title="Excavadora de prueba",data={"location":"Querétaro","serial":"SERIE-PRIVADA","notes":"NOTA-INTERNA"})
        raw=BytesIO();Image.new("RGB",(64,64),"#999999").save(raw,format="JPEG")
        self.photo=Asset(machine=self.machine,kind="image",purpose="general",processing_status="ready",mime_type="image/jpeg",sha256="a"*64,size=len(raw.getvalue()))
        self.photo.original.save("test.jpg",ContentFile(raw.getvalue()),save=False)
        self.photo.preview.save("preview.jpg",ContentFile(raw.getvalue()),save=False)
        self.photo.save()
        self.base=f"/api/maquinarias/{self.machine.pk}"

    def post_json(self,url,data,client=None):
        return (client or self.client).post(url,json.dumps(data),content_type="application/json")

    def verified_login(self,user,client=None):
        client=client or self.client
        client.force_login(user)
        device=TOTPDevice.objects.create(user=user,name="IMC",confirmed=True)
        session=client.session
        session[DEVICE_ID_SESSION_KEY]=device.persistent_id
        session.save()
        return device

    def approved(self):
        set_advertiser_status(self.owner,self.admin,"approved","Validado en prueba")
        sub=submit_machine(self.machine,self.owner,True)
        self.photo.public_authorized=True;self.photo.save()
        record_local_duplicate_review(
            self.machine, sub, self.admin, "no_match",
            "Se revisaron identidad, archivos y datos de la ficha enviada.",
        )
        review_submission(sub,self.admin,"approved")
        self.machine.refresh_from_db()
        return sub,set_publication(self.machine,self.admin,True)

    def test_anonymous_api_and_private_files_require_login(self):
        response=self.post_json(self.base+"/guardar/",{"revision":1,"title":"No autorizado"})
        self.assertEqual(response.status_code,401)
        self.assertEqual(self.client.get(f"/archivos/{self.photo.pk}/").status_code,302)
        self.assertEqual(self.client.get(f"/panel/maquinarias/{self.machine.pk}/").status_code,302)

    def test_csrf_rejects_authenticated_mutations(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for url,data in [(self.base+"/guardar/",{"revision":1,"title":"X"}),(self.base+"/enviar/",{"advertise_consent":True}),(self.base+"/accion/",{"action":"availability","value":"sold"}), ("/api/maquinarias/",{})]:
            self.assertEqual(self.post_json(url,data,client).status_code,403)
        response=client.get(f"/panel/maquinarias/{self.machine.pk}/")
        self.assertEqual(response.status_code,200)
        token=client.cookies["csrftoken"].value
        response=client.post(self.base+"/guardar/",json.dumps({"revision":1,"title":"Guardado con CSRF"}),content_type="application/json",HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code,200)

    def test_idor_denies_other_user_data_and_jobs(self):
        job=AnalysisJob.objects.create(machine=self.machine,requested_by=self.owner,revision=1,fingerprint="b"*64)
        self.client.force_login(self.other)
        for url in [f"/panel/maquinarias/{self.machine.pk}/",f"/panel/maquinarias/{self.machine.pk}/ficha/",f"/archivos/{self.photo.pk}/",f"/api/analisis/{job.pk}/"]:
            self.assertEqual(self.client.get(url).status_code,404,url)
        self.assertEqual(self.client.get(f"/panel/maquinarias/{self.machine.pk}/pdf/").status_code,403)
        self.assertEqual(self.post_json(self.base+"/guardar/",{"revision":1,"title":"Ajena"}).status_code,404)

    def test_normal_account_cannot_access_operations_or_admin(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/operaciones/").status_code,403)
        self.assertEqual(self.client.get("/admin/").status_code,302)

    def test_admin_login_uses_central_rate_limited_login(self):
        self.assertRedirects(self.client.get("/admin/login/"),"/administracion/",fetch_redirect_response=False)

    def test_activation_tokens_not_visible_in_admin_notifications(self):
        self.verified_login(self.admin)
        notification=Notification.objects.create(user=self.owner,kind="recovery",subject="Recuperación",body="PRIVATE-ACTIVATION-TOKEN",channel="email")
        response=self.client.get("/admin/portal/notification/")
        self.assertNotContains(response,"PRIVATE-ACTIVATION-TOKEN")
        self.assertEqual(self.client.get(f"/admin/portal/notification/{notification.pk}/change/").status_code,302)

    def test_unverified_staff_cannot_cross_owner_boundary(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get("/admin/"),"/panel/seguridad/?next=/admin/",fetch_redirect_response=False)
        self.assertEqual(self.client.get("/operaciones/").status_code,302)
        self.assertEqual(self.client.get(f"/archivos/{self.photo.pk}/").status_code,404)
        self.assertEqual(self.post_json(self.base+"/guardar/",{"revision":1,"title":"Sin OTP"}).status_code,404)

    def test_verified_staff_read_permission_does_not_grant_edit(self):
        self.verified_login(self.operator)
        self.assertEqual(self.client.get(f"/panel/maquinarias/{self.machine.pk}/ficha/").status_code,200)
        response=self.post_json(f"/api/archivos/{self.photo.pk}/accion/",{"action":"delete"})
        self.assertEqual(response.status_code,403)
        self.assertTrue(Asset.objects.filter(pk=self.photo.pk).exists())
        self.assertEqual(self.post_json(self.base+"/guardar/",{"revision":1,"title":"No"}).status_code,403)

    def test_verified_admin_and_all_model_change_pages_render(self):
        self.verified_login(self.admin)
        self.assertEqual(self.client.get("/admin/").status_code,200)
        self.assertEqual(self.client.get("/operaciones/").status_code,200)
        for url in [f"/admin/portal/user/{self.owner.pk}/change/",f"/admin/portal/asset/{self.photo.pk}/change/",f"/admin/portal/machine/{self.machine.pk}/change/"]:
            self.assertEqual(self.client.get(url).status_code,200,url)

    def test_otp_real_code_verifies_and_cannot_be_replayed(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/panel/seguridad/").status_code,200)
        device=TOTPDevice.objects.get(user=self.admin,name="IMC")
        token=f"{totp(device.bin_key,step=device.step,t0=device.t0,digits=device.digits):06d}"
        self.assertEqual(self.client.post("/panel/seguridad/",{"action":"otp","token":token}).status_code,302)
        self.assertEqual(self.client.get("/admin/").status_code,200)
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertFalse(device.verify_token(token))

    def test_profile_mass_assignment_cannot_elevate_or_verify(self):
        self.client.force_login(self.owner)
        response=self.client.post("/panel/perfil/",{"first_name":"Nombre","last_name":"","phone":"+525512345678","company":"","contact_preference":"email","is_superuser":"on","is_staff":"on","advertiser_status":"approved","email_verified":"on","email":"attacker@example.com"})
        self.assertEqual(response.status_code,302)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_staff)
        self.assertFalse(self.owner.is_superuser)
        self.assertFalse(self.owner.email_verified)
        self.assertEqual(self.owner.advertiser_status,"pending")
        self.assertEqual(self.owner.email,"owner@example.com")

    def test_registration_creates_regular_account_consents_and_real_mail_job(self):
        configuration=PlatformSettings.objects.create()
        self.assertFalse(configuration.legal_validated)
        self.assertContains(self.client.get("/registro/"),"Crear mi cuenta")
        response=self.client.post("/registro/",{"first_name":"Prueba","last_name":"Cuenta","email":"New@Example.com","phone":"+52 55 1234 5678","contact_preference":"email","password1":"New-password-long123!","password2":"New-password-long123!","terms":"on","is_superuser":"on","is_staff":"on","advertiser_status":"approved","email_verified":"on"})
        self.assertRedirects(response,"/panel/")
        user=User.objects.get(email="new@example.com")
        self.assertEqual(str(user.pk),self.client.session["_auth_user_id"])
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.email_verified)
        self.assertEqual(user.advertiser_status,"pending")
        self.assertEqual(user.consents.count(),2)
        self.assertTrue(Notification.objects.filter(user=user,kind="verify",status="pending").exists())
        self.assertTrue(AuditEvent.objects.filter(actor=user,action="account.register").exists())
        response=self.post_json("/api/maquinarias/",{})
        self.assertEqual(response.status_code,201)
        self.assertTrue(Machine.objects.filter(owner=user,status="draft").exists())
        self.assertEqual(self.client.get("/operaciones/").status_code,403)
        self.client.post("/cerrar-sesion/")
        self.assertRedirects(self.client.post("/iniciar-sesion/",{"username":"NEW@example.com","password":"New-password-long123!"}),"/panel/")
        configuration.refresh_from_db()
        self.assertFalse(configuration.legal_validated)

    def test_registration_can_be_paused_without_blocking_existing_accounts(self):
        configuration=PlatformSettings.objects.create(registration_open=False)
        payload={"first_name":"Prueba","last_name":"Cuenta","email":"closed@example.com","phone":"+525512345678","contact_preference":"email","password1":"New-password-long123!","password2":"New-password-long123!","terms":"on"}
        for legal_value in (False,True):
            with self.subTest(legal_validated=legal_value):
                configuration.legal_validated=legal_value;configuration.save()
                self.assertContains(self.client.get("/registro/"),"todavía no está abierto")
                response=self.client.post("/registro/",payload)
                self.assertContains(response,"todavía no está abierto")
                self.assertFalse(User.objects.filter(email="closed@example.com").exists())
        self.assertRedirects(self.client.post("/iniciar-sesion/",{"username":self.owner.email,"password":"Owner-password-long123"}),"/panel/")

    def test_registration_without_seed_requires_csrf_and_accepts_valid_form(self):
        self.assertFalse(PlatformSettings.objects.exists())
        client=Client(enforce_csrf_checks=True)
        response=client.get("/registro/")
        self.assertContains(response,'name="password1"')
        self.assertContains(response,'name="terms"')
        payload={"first_name":"Prueba","last_name":"Cuenta","email":"unseeded@example.com","phone":"+525512345678","contact_preference":"email","password1":"New-password-long123!","password2":"New-password-long123!","terms":"on"}
        self.assertEqual(client.post("/registro/",payload).status_code,403)
        self.assertFalse(User.objects.filter(email=payload["email"]).exists())
        payload["csrfmiddlewaretoken"]=client.cookies["csrftoken"].value
        response=client.post("/registro/",payload)
        self.assertRedirects(response,"/panel/",fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(email=payload["email"]).exists())

    def test_registration_rejects_duplicate_email_and_missing_consent(self):
        payload={"first_name":"Prueba","last_name":"Cuenta","email":"OWNER@EXAMPLE.COM","phone":"+525512345678","contact_preference":"email","password1":"New-password-long123!","password2":"New-password-long123!","terms":"on"}
        count=User.objects.count()
        response=self.client.post("/registro/",payload)
        self.assertContains(response,"Ya existe una cuenta con este correo")
        payload["email"]="no-consent@example.com"
        payload.pop("terms")
        response=self.client.post("/registro/",payload)
        self.assertEqual(response.status_code,200)
        self.assertIn("terms",response.context["form"].errors)
        self.assertEqual(User.objects.count(),count)
        self.assertFalse(Notification.objects.filter(kind="verify").exists())

    def test_recovery_response_does_not_reveal_account_existence(self):
        self.assertEqual(self.client.post("/recuperar-acceso/",{"email":self.owner.email}).status_code,302)
        self.assertEqual(self.client.post("/recuperar-acceso/",{"email":"absent@example.com"}).status_code,302)
        self.assertEqual(Notification.objects.filter(kind="recovery").count(),1)

    def test_activation_token_single_use_and_session_invalidation(self):
        old_client=Client();old_client.force_login(self.owner)
        token=default_token_generator.make_token(self.owner)
        uid=urlsafe_base64_encode(force_bytes(self.owner.pk))
        url=f"/activar/{uid}/{token}/"
        response=self.client.post(url,{"new_password1":"Changed-password-long456!","new_password2":"Changed-password-long456!"})
        self.assertEqual(response.status_code,302)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.email_verified)
        self.assertTrue(self.owner.check_password("Changed-password-long456!"))
        self.assertFalse(default_token_generator.check_token(self.owner,token))
        self.assertEqual(old_client.get("/panel/").status_code,302)

    def test_login_next_cannot_redirect_off_site(self):
        response=self.client.post("/iniciar-sesion/?next=https://evil.example/",{"username":self.owner.email,"password":"Owner-password-long123"})
        self.assertRedirects(response,"/panel/",fetch_redirect_response=False)

    def test_login_throttle_blocks_correct_password_after_threshold(self):
        for _ in range(12):
            self.client.post("/iniciar-sesion/",{"username":self.owner.email,"password":"wrong"})
        response=self.client.post("/iniciar-sesion/",{"username":self.owner.email,"password":"Owner-password-long123"})
        self.assertEqual(response.status_code,200)
        self.assertNotIn("_auth_user_id",self.client.session)

    def test_logout_requires_post(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/cerrar-sesion/").status_code,405)
        self.assertEqual(self.client.post("/cerrar-sesion/").status_code,302)

    def test_internal_messages_never_appear_in_owner_panel(self):
        Message.objects.create(machine=self.machine,sender=self.admin,body="Mensaje autorizado")
        Message.objects.create(machine=self.machine,sender=self.admin,body="SECRETO-OPERACION",internal=True)
        self.client.force_login(self.owner)
        response=self.client.get("/panel/mensajes/")
        self.assertContains(response,"Mensaje autorizado")
        self.assertNotContains(response,"SECRETO-OPERACION")

    def test_unknown_api_fields_and_stale_save_are_rejected(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.post_json(self.base+"/guardar/",{"revision":1,"status":"approved"}).status_code,400)
        self.assertEqual(self.post_json(self.base+"/enviar/",{"advertise_consent":True,"approved":True}).status_code,400)
        self.assertEqual(self.post_json(self.base+"/guardar/",{"revision":0,"title":"stale"}).status_code,409)

    def test_api_ai_apply_cannot_accept_client_values_or_other_job(self):
        self.client.force_login(self.owner)
        job=AnalysisJob.objects.create(machine=self.machine,requested_by=self.owner,revision=1,fingerprint="c"*64,status="completed",result={"data":{"brand":"Visible"},"provenance":{"brand":{"source":"image","asset_id":str(self.photo.pk),"review":"clear"}}})
        self.assertEqual(self.post_json(self.base+"/aplicar/",{"job_id":str(job.pk),"fields":["brand"],"revision":1,"data":{"brand":"Injected"}}).status_code,400)
        response=self.post_json(self.base+"/aplicar/",{"job_id":str(job.pk),"fields":["brand"],"revision":1})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["data"]["brand"],"Visible")

    def test_asset_change_invalidates_previous_analysis_revision(self):
        self.client.force_login(self.owner)
        job=AnalysisJob.objects.create(machine=self.machine,requested_by=self.owner,revision=1,fingerprint="d"*64,status="completed",result={"data":{"brand":"Anterior"},"provenance":{"brand":{"source":"image","asset_id":str(self.photo.pk),"review":"clear"}}})
        response=self.post_json(f"/api/archivos/{self.photo.pk}/accion/",{"action":"purpose","purpose":"plate"})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["revision"],2)
        response=self.post_json(self.base+"/aplicar/",{"job_id":str(job.pk),"fields":["brand"],"revision":2})
        self.assertEqual(response.status_code,400)
        self.machine.refresh_from_db()
        self.assertNotIn("brand",self.machine.data)

    def test_public_sheet_redacts_private_values_and_never_uses_draft(self):
        _,publication=self.approved()
        self.machine.title="TITULO-SIN-REVISAR";self.machine.save()
        response=self.client.get(f"/ficha/{publication.token}/")
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Excavadora de prueba")
        self.assertNotContains(response,"TITULO-SIN-REVISAR")
        self.assertNotContains(response,"SERIE-PRIVADA")
        self.assertNotContains(response,"NOTA-INTERNA")
        self.assertEqual(response["Cache-Control"],"no-store")

    def test_public_media_requires_allowlist_authorization_and_live_permission(self):
        _,publication=self.approved()
        response=self.client.get(f"/ficha/{publication.token}/archivo/{self.photo.pk}/")
        self.assertEqual(response.status_code,200);response.close()
        self.photo.public_authorized=False;self.photo.save()
        self.assertEqual(self.client.get(f"/ficha/{publication.token}/archivo/{self.photo.pk}/").status_code,404)
        self.owner.advertiser_status="suspended";self.owner.save()
        self.assertEqual(self.client.get(f"/ficha/{publication.token}/").status_code,404)

    def test_publication_token_alone_is_not_authorization(self):
        publication=Publication.objects.create(machine=self.machine)
        self.assertEqual(self.client.get(f"/ficha/{publication.token}/").status_code,404)
        self.assertEqual(self.client.get(f"/ficha/{publication.token}/pdf/").status_code,404)

    def test_contact_cannot_link_private_machine_from_anonymous_or_other_user(self):
        data={"name":"Consulta","email":"lead@example.com","phone":"","message":"Información","privacy":"on","machine":str(self.machine.pk)}
        self.assertEqual(self.client.get(f"/contacto/?maquinaria={self.machine.pk}").status_code,404)
        self.assertEqual(self.client.post("/contacto/",data).status_code,404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post("/contacto/",data).status_code,404)
        self.assertFalse(Lead.objects.exists())

    def test_owner_contact_links_own_machine_and_test_classification(self):
        self.owner.is_test=True;self.owner.save()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(f"/contacto/?maquinaria={self.machine.pk}").status_code,200)
        response=self.client.post("/contacto/",{"name":"Consulta","email":"owner@example.com","phone":"","message":"Ayuda","privacy":"on","machine":str(self.machine.pk)})
        self.assertEqual(response.status_code,302)
        lead=Lead.objects.get()
        self.assertEqual(lead.machine_id,self.machine.pk)
        self.assertEqual(lead.user_id,self.owner.pk)
        self.assertTrue(lead.is_test)

    def test_anonymous_contact_links_current_public_version_and_disabled_denied(self):
        _,publication=self.approved()
        self.machine.title="BORRADOR-PRIVADO";self.machine.save()
        response=self.client.get(f"/contacto/?maquinaria={self.machine.pk}")
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,"BORRADOR-PRIVADO")
        response=self.client.post("/contacto/",{"name":"Consulta","email":"lead@example.com","phone":"","message":"Información","privacy":"on","machine":str(self.machine.pk)})
        self.assertEqual(response.status_code,302)
        self.assertEqual(Lead.objects.get().machine_id,self.machine.pk)
        publication.enabled=False;publication.save()
        self.assertEqual(self.client.get(f"/contacto/?maquinaria={self.machine.pk}").status_code,404)

    def test_retained_assets_cannot_be_deleted(self):
        self.approved()
        self.client.force_login(self.owner)
        response=self.post_json(f"/api/archivos/{self.photo.pk}/accion/",{"action":"delete"})
        self.assertEqual(response.status_code,400)
        self.assertTrue(Asset.objects.filter(pk=self.photo.pk).exists())

    def test_duplicate_gets_new_private_files_and_no_publication(self):
        _,publication=self.approved()
        self.client.force_login(self.owner)
        response=self.post_json(self.base+"/accion/",{"action":"duplicate"})
        self.assertEqual(response.status_code,200)
        duplicate=Machine.objects.get(pk=response.json()["id"])
        self.assertEqual(duplicate.status,"draft")
        self.assertIsNone(duplicate.approved_version_id)
        asset=duplicate.assets.get()
        self.assertFalse(asset.public_authorized)
        self.assertNotEqual(asset.original.name,self.photo.original.name)
        self.assertNotEqual(asset.pk,self.photo.pk)
        with asset.original.open("rb") as stream:self.assertGreater(len(stream.read()),0)
        self.assertFalse(duplicate.publications.exists())

    def test_export_preserves_external_publication_confirmation(self):
        self.approved()
        self.verified_login(self.admin)
        main=Publication.objects.create(machine=self.machine,destination="main",version=self.machine.approved_version,status="published",external_id="confirmed-123",external_url="https://example.com/machine")
        with patch("portal.pdf.build_pdf",return_value=b"%PDF-1.4\n"):
            response=self.client.post(f"/operaciones/maquinarias/{self.machine.pk}/exportar/")
        # Preparing the package creates a local handoff candidate.  It must
        # not export until a separate IMC duplicate review is recorded.
        self.assertEqual(response.status_code,302)
        main.refresh_from_db()
        self.assertEqual(main.status,"published")
        self.assertEqual(main.external_id,"confirmed-123")
