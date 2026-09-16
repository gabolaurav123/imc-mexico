"""Integration regression for the two-step, private machinery intake flow.

The provider is mocked only at its processing boundary; uploads, saved drafts,
consents, queued work and submissions use the real application endpoints.
"""
from html.parser import HTMLParser
from io import BytesIO,StringIO
import json
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client,TestCase,override_settings
from PIL import Image

from portal.models import (AnalysisJob,Asset,Consent,Machine,MachineVersion,
                           Notification,PlatformSettings,Publication,SiteContent,Submission,User)
from portal.processing import process_next_job


class IntakeHTML(HTMLParser):
    def __init__(self):
        super().__init__();self.panels=[];self.step_targets=set();self.inputs={};self.checkboxes=[];self.details={};self.scripts=[]

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'data-step-panel' in attrs:self.panels.append(attrs['data-step-panel'])
        if 'data-step-to' in attrs:self.step_targets.add(attrs['data-step-to'])
        if tag=='input' and attrs.get('id'):self.inputs[attrs['id']]=attrs
        if tag=='input' and attrs.get('type')=='checkbox':self.checkboxes.append(attrs)
        if tag=='details' and attrs.get('id'):self.details[attrs['id']]=attrs
        if tag=='script' and attrs.get('src'):self.scripts.append(attrs['src'])


@override_settings(OPENAI_API_KEY='test-not-a-real-key',OPENAI_MODEL='gpt-4.1-mini',
    PRIVATE_S3_BUCKET='',SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    STORAGES={'default':{'BACKEND':'portal.storage.PrivateStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class QuickIntakeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner=User.objects.create_user(email='quick-intake@example.invalid',password=None,is_test=True)

    def setUp(self):
        directory=TemporaryDirectory(prefix='imc-quick-intake-')
        self.addCleanup(directory.cleanup)
        media=override_settings(MEDIA_ROOT=directory.name);media.enable();self.addCleanup(media.disable)
        self.platform=PlatformSettings.objects.create(ai_enabled=True,ai_daily_token_limit=1000000)
        self.client.force_login(self.owner)
        response=self.post('/api/maquinarias/',{})
        self.assertEqual(response.status_code,201)
        self.machine=Machine.objects.get(pk=response.json()['id'])
        self.base=f'/api/maquinarias/{self.machine.pk}'

    def post(self,url,data,client=None,**kwargs):
        return (client or self.client).post(url,json.dumps(data),content_type='application/json',**kwargs)

    def upload(self,purpose='general'):
        buffer=BytesIO();Image.new('RGB',(96,64),'#627884').save(buffer,format='JPEG')
        response=self.client.post(self.base+'/archivos/',{'file':SimpleUploadedFile('maquina-sintetica.jpg',buffer.getvalue(),content_type='image/jpeg'),'purpose':purpose})
        self.assertEqual(response.status_code,201)
        self.machine.refresh_from_db()
        return Asset.objects.get(pk=response.json()['id'])

    def save_manual(self,**data):
        self.machine.refresh_from_db()
        response=self.post(self.base+'/guardar/',{'revision':self.machine.revision,'title':'Maquinaria declarada por el anunciante','data':{'location':'Querétaro, México','year':None,'hours':None,'serial':None,**data}})
        self.assertEqual(response.status_code,200,response.content)
        self.machine.refresh_from_db()

    def test_wizard_has_two_steps_without_analysis_or_publication_checklists(self):
        response=self.client.get(f'/panel/maquinarias/{self.machine.pk}/')
        self.assertEqual(response.status_code,200)
        dom=IntakeHTML();dom.feed(response.content.decode())
        self.assertEqual(dom.panels,['1','2'])
        self.assertEqual(dom.step_targets,{'1','2'})
        for obsolete in ('ai-consent','advertise-consent','no-plate'):
            self.assertNotIn(obsolete,dom.inputs)
        checkboxes={attrs.get('id') for attrs in dom.checkboxes}
        self.assertEqual(checkboxes,{'contact-consent'})
        self.assertNotIn('checked',dom.inputs['contact-consent'])
        self.assertIn('contact-details',dom.details)
        self.assertNotIn('open',dom.details['contact-details'])
        self.assertContains(response,'OpenAI')
        self.assertContains(response,'Enviar a IMC México')
        self.assertNotContains(response,'id="analysis-assets"')
        self.assertFalse(AnalysisJob.objects.exists())
        self.assertFalse(Submission.objects.exists())

    def test_preparing_and_polling_autofill_keeps_everything_private(self):
        asset=self.upload()
        response=self.post(self.base+'/analizar/',{'consent':True,'auto_apply':True,'revision':self.machine.revision})
        self.assertEqual(response.status_code,200,response.content)
        job_id=response.json()['id']
        self.assertTrue(Consent.objects.filter(user=self.owner,machine=self.machine,kind='ai',granted=True).exists())
        self.assertFalse(Consent.objects.filter(machine=self.machine,kind='advertise').exists())
        result={'data':{'title':'Maquinaria observada','description':'Vista general de maquinaria.','brand':'MARCA DE PRUEBA','serial':None,'year':None,'hours':None},
                'provenance':{'brand':{'source':'image','review':'clear','asset_id':str(asset.pk),'component':'machine','evidence':'MARCA DE PRUEBA'}},
                'plates':[],'warnings':[],'questions':[]}
        with patch('portal.processing.process_analysis',return_value=(result,SimpleNamespace(input_tokens=10,output_tokens=10))):
            self.assertTrue(process_next_job())
        response=self.client.get(f'/api/analisis/{job_id}/')
        self.assertEqual(response.status_code,200)
        body=response.json()
        self.assertEqual(body['status'],'completed')
        self.assertEqual(body['machine']['data']['brand'],'MARCA DE PRUEBA')
        self.assertEqual(body['auto_apply']['status'],'applied')
        self.machine.refresh_from_db();asset.refresh_from_db();self.owner.refresh_from_db()
        self.assertEqual(self.machine.status,'draft')
        self.assertIsNone(self.machine.approved_version_id)
        self.assertFalse(asset.public_authorized)
        self.assertEqual(self.owner.advertiser_status,'pending')
        for model in (Submission,MachineVersion,Publication):self.assertFalse(model.objects.exists())
        anonymous=Client()
        self.assertEqual(anonymous.get(f'/archivos/{asset.pk}/').status_code,302)
        self.assertEqual(anonymous.get(f'/panel/maquinarias/{self.machine.pk}/').status_code,302)

    def test_quota_failure_preserves_upload_and_allows_submission_without_manual_specs(self):
        asset=self.upload()
        self.platform.ai_user_daily_limit=0;self.platform.save(update_fields=['ai_user_daily_limit'])
        response=self.post(self.base+'/analizar/',{'consent':True,'auto_apply':True,'revision':self.machine.revision})
        self.assertEqual(response.status_code,400)
        self.assertIn('enviar la ficha con la información disponible',response.json()['error'].lower())
        self.assertFalse(AnalysisJob.objects.exists())
        asset.refresh_from_db();self.assertTrue(asset.original.storage.exists(asset.original.name))
        self.assertEqual(self.machine.assets.count(),1)
        response=self.post(self.base+'/enviar/',{'advertise_consent':True,'contact_consent':False})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(Submission.objects.count(),1)
        self.assertFalse(Publication.objects.exists())
        self.machine.refresh_from_db()
        for field in ('year','hours','serial'):self.assertIsNone(self.machine.data.get(field))

    def test_explicit_final_action_is_required_and_repeat_does_not_duplicate_submission(self):
        self.upload();self.save_manual(contact_public='Este texto no autoriza su difusión')
        response=self.post(self.base+'/enviar/',{})
        self.assertEqual(response.status_code,400)
        self.assertFalse(Submission.objects.exists())
        response=self.post(self.base+'/enviar/',{'advertise_consent':True,'contact_consent':False})
        self.assertEqual(response.status_code,200,response.content)
        first=Submission.objects.get()
        response=self.post(self.base+'/enviar/',{'advertise_consent':True,'contact_consent':False})
        self.assertIn(response.status_code,(200,400,409))
        self.assertEqual(Submission.objects.count(),1)
        self.assertEqual(MachineVersion.objects.count(),1)
        self.assertEqual(Consent.objects.filter(machine=self.machine,kind='advertise',granted=True).count(),1)
        self.assertEqual(Notification.objects.filter(machine=self.machine,kind='submission',channel='email').count(),1)
        self.assertFalse(first.version.data['contact_authorized'])
        self.assertEqual(first.version.data.get('public_contact'),{})
        self.assertFalse(Publication.objects.exists())
        self.assertFalse(Consent.objects.filter(user=self.owner,kind='marketing').exists())
        self.machine.refresh_from_db();self.assertEqual(self.machine.status,'submitted')

    def test_missing_location_can_be_submitted_without_inventing_it_or_publishing(self):
        asset=self.upload();self.save_manual(location='')
        response=self.post(self.base+'/enviar/',{'advertise_consent':True,'contact_consent':False})
        self.assertEqual(response.status_code,200,response.content)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.status,'submitted')
        self.assertEqual(self.machine.data.get('location'),'')
        self.assertTrue(self.machine.assets.filter(pk=asset.pk).exists())
        submission=Submission.objects.get(machine=self.machine)
        self.assertEqual(submission.version.data['data'].get('location'),'')
        self.assertFalse(Publication.objects.exists())

    def test_photos_and_consent_are_enough_with_neutral_fallback_and_immutable_snapshot(self):
        self.upload();before=self.machine.revision
        response=self.post(self.base+'/enviar/',{'advertise_consent':True,'contact_consent':False})
        self.assertEqual(response.status_code,200,response.content)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.title,'Maquinaria para revisión')
        self.assertIn('pendientes de confirmar',self.machine.data['description'])
        self.assertEqual(self.machine.revision,before+1)
        self.assertNotIn('location',self.machine.data)
        submission=Submission.objects.get(machine=self.machine)
        self.assertEqual(submission.version.data['revision'],self.machine.revision)
        self.assertEqual(submission.version.data['title'],self.machine.title)
        self.assertEqual(submission.version.data['provenance']['description'],{'source':'system','review':'needs_review'})
        self.assertFalse(Publication.objects.exists())
        self.assertFalse(AnalysisJob.objects.exists())

    def test_simplified_actions_still_require_csrf(self):
        self.upload();self.save_manual()
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.owner)
        for endpoint,payload in [('analizar',{'consent':True,'auto_apply':True,'revision':self.machine.revision}),('enviar',{'advertise_consent':True,'contact_consent':False})]:
            self.assertEqual(self.post(self.base+'/'+endpoint+'/',payload,csrf).status_code,403)
        self.assertFalse(AnalysisJob.objects.exists())
        self.assertFalse(Submission.objects.exists())
        self.assertFalse(Consent.objects.filter(machine=self.machine).exists())


@override_settings(SECURE_SSL_REDIRECT=False,STORAGES={
    'default':{'BACKEND':'portal.storage.PrivateStorage'},
    'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class QuickIntakeContentSeedTests(TestCase):
    legacy_title='Tus fotos, una ficha más clara'
    legacy_body='Sube una fotografía general de tu maquinaria. La placa ayuda, pero no es obligatoria. Revisa cada dato propuesto por la IA, completa la ubicación y envía tu solicitud. El equipo de IMC México revisa tu permiso de anunciante y el contenido antes de autorizar una publicación.'

    def seed(self):
        call_command('seed',stdout=StringIO())

    def test_seed_upgrades_untouched_live_text_idempotently_and_renders_two_steps(self):
        content=SiteContent.objects.create(key='como-funciona',title=self.legacy_title,body=self.legacy_body,active=True)
        legal=SiteContent.objects.create(key='privacidad',title='Aviso revisado por el equipo',body='Texto legal propio.',active=True)
        self.seed()
        content.refresh_from_db();legal.refresh_from_db()
        expected=(content.title,content.body,content.active)
        self.assertIn('dos pasos',content.title)
        self.assertIn('01 · Sube tus fotos',content.body)
        self.assertIn('02 · Envía tu ficha',content.body)
        self.assertNotIn('Revisa cada dato propuesto',content.body)
        self.assertEqual((legal.title,legal.body,legal.active),('Aviso revisado por el equipo','Texto legal propio.',True))
        self.seed()
        content.refresh_from_db()
        self.assertEqual((content.title,content.body,content.active),expected)
        self.assertEqual(SiteContent.objects.filter(key='como-funciona').count(),1)
        self.assertFalse(Machine.objects.exists())
        response=self.client.get('/como-funciona/')
        self.assertContains(response,'01 · Sube tus fotos')
        self.assertContains(response,'02 · Envía tu ficha')
        content.delete()
        self.seed()
        fresh=SiteContent.objects.get(key='como-funciona')
        self.assertEqual((fresh.title,fresh.body,fresh.active),expected)

    def test_seed_preserves_admin_title_body_and_disabled_legacy_content(self):
        content=SiteContent.objects.create(key='como-funciona',title=self.legacy_title,body=self.legacy_body)
        for title,body,active in [
            ('Título del equipo',self.legacy_body,True),
            (self.legacy_title,'Instrucciones editadas por el equipo.',True),
            (self.legacy_title,self.legacy_body,False),
        ]:
            with self.subTest(title=title,active=active):
                SiteContent.objects.filter(pk=content.pk).update(title=title,body=body,active=active)
                self.seed();self.seed()
                content.refresh_from_db()
                self.assertEqual((content.title,content.body,content.active),(title,body,active))
