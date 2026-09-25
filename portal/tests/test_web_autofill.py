"""Business and publication checks for signed, scoped web suggestions."""
from copy import deepcopy
from io import BytesIO
import json
from tempfile import TemporaryDirectory
import uuid
import zipfile

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from PIL import Image
from pypdf import PdfReader

from portal.models import AnalysisJob, Asset, Consent, IntegrationDelivery, Machine, Publication, User
from portal.integration import record_manual_review
from portal.pdf import build_pdf
from portal.research import ResearchExtraction, ResearchField, merge_research, normalize_research
from portal.services import (apply_analysis_automatically, apply_analysis_suggestions,
    automatic_application_snapshot, public_web_references, record_local_duplicate_review, review_submission,
    save_draft, set_advertiser_status, set_publication, submit_machine)


@override_settings(SECURE_SSL_REDIRECT=False, STAFF_MFA_REQUIRED=False, PRIVATE_S3_BUCKET='',
    STORAGES={'default':{'BACKEND':'portal.storage.PrivateStorage'},
              'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class WebAutofillTests(TestCase):
    def setUp(self):
        directory=TemporaryDirectory(prefix='imc-web-reference-test-')
        self.addCleanup(directory.cleanup)
        media=override_settings(MEDIA_ROOT=directory.name);media.enable();self.addCleanup(media.disable)
        self.owner=User.objects.create_user(email='web-owner@example.invalid',is_test=True)
        self.admin=User.objects.create_superuser(email='web-reviewer@example.invalid',password=None,is_test=True)
        self.machine=Machine.objects.create(owner=self.owner,title='Equipo de prueba',
            data={'brand':'Caterpillar','model':'420F2','serial':'CAT-SN1234'})
        raw=BytesIO();Image.new('RGB',(60,40),'gray').save(raw,format='JPEG')
        self.asset=Asset(machine=self.machine,kind='image',purpose='general',processing_status='ready',
                         mime_type='image/jpeg',sha256='a'*64,size=len(raw.getvalue()))
        self.asset.original.save('machine.jpg',ContentFile(raw.getvalue()),save=False)
        self.asset.preview.save('preview.jpg',ContentFile(raw.getvalue()),save=False)
        self.asset.save()
        Consent.objects.create(user=self.owner,machine=self.machine,kind='ai',granted=True)

    def result(self, specs=None, scope='model', urls=None, titles=None):
        specs=specs or {'power':'70 kW','weight':'8000 kg'}
        identity={'brand':'Caterpillar','model':'420F2','serial':'CAT-SN1234' if scope=='exact_serial' else None}
        fields=[];sources=[];passages=[]
        for key,value in specs.items():
            url=(urls or {}).get(key,'https://www.cat.com/equipment/420f2.html')
            title=(titles or {}).get(key,'Caterpillar 420F2 · Especificaciones')
            label='bucket capacity' if key=='capacity' else key
            passage=f"Caterpillar 420F2 {identity['serial'] or ''}: {label} {value}."
            fields.append(ResearchField(key=key,value=value,scope=scope,source_url=url,evidence=passage,
                matched_serial=identity['serial'],matched_brand='Caterpillar',matched_model='420F2'))
            if not any(item['url']==url for item in sources):sources.append({'url':url,'title':title})
            passages.append(f'{passage} [Fuente]({url})')
        research=normalize_research(ResearchExtraction(fields=fields),identity,scope,sources,'\n\n'.join(passages))
        return merge_research({'data':{},'provenance':{},'fields':[],'plates':[],'warnings':[]},research)

    def job(self,result):
        return AnalysisJob.objects.create(machine=self.machine,requested_by=self.owner,
            revision=self.machine.revision,asset_ids=[str(self.asset.pk)],fingerprint=uuid.uuid4().hex,
            status='completed',auto_apply=True,application_snapshot=automatic_application_snapshot(self.machine),result=result)

    def apply(self,job):
        self.machine,summary=apply_analysis_automatically(self.machine,self.owner,job,self.machine.revision)
        return summary

    def test_verified_model_specs_fill_gaps_with_source_and_cautious_description(self):
        summary=self.apply(self.job(self.result()))
        self.assertIn('power',summary['applied_fields'])
        self.assertEqual(self.machine.data['power'],'70 kW')
        self.assertEqual(self.machine.provenance['power']['source'],'web')
        self.assertEqual(self.machine.provenance['power']['scope'],'model')
        self.assertEqual(self.machine.provenance['power']['review'],'needs_review')
        self.assertIn('70 kW',self.machine.data['description'])
        self.assertIn('requieren comprobación',self.machine.data['description'])
        self.assertNotIn('CAT-SN1234',self.machine.data['description'])
        self.assertFalse(Publication.objects.exists())

    def test_disabled_research_keeps_the_original_visual_description(self):
        original='Excavadora con brazo articulado y cucharón visibles en las fotografías.'
        result={'data':{'description':original},
                'provenance':{'description':{'source':'visual_proposal','review':'needs_review'}},
                'research':{'status':'disabled','fields':[],'sources':[]}}
        summary=self.apply(self.job(result))
        self.assertIn('description',summary['applied_fields'])
        self.assertEqual(self.machine.data['description'],original)
        self.assertEqual(self.machine.provenance['description']['source'],'visual_proposal')

    def test_forged_proof_or_changed_source_never_applies_web_value(self):
        for change in ('proof','source_url'):
            with self.subTest(change=change):
                result=self.result({'power':'70 kW'})
                if change=='proof':result['research']['proof']='forged'
                else:result['provenance']['power']['source_url']='https://unrelated.com/specs'
                summary=self.apply(self.job(result))
                self.assertNotIn('power',self.machine.data)
                self.assertNotIn('power',summary['applied_fields'])
                self.assertNotIn('70 kW',self.machine.data.get('description',''))

    def test_model_year_and_unit_operating_data_are_not_web_autofill_fields(self):
        result=self.result({'year':'2020','hours':'1000','price':'10000','location':'Monterrey','serial':'WEB-9999','power':'70 kW'})
        self.assertEqual([field['key'] for field in result['research']['fields']],['power'])
        # Untrusted candidates cannot use a genuine proof for a different field.
        result['data'].update(year='2020',hours='1000',location='Monterrey',serial='WEB-9999')
        for key in ('year','hours','location','serial'):
            result['provenance'][key]=deepcopy(result['provenance']['power'])
        summary=self.apply(self.job(result))
        for key in ('year','hours','location','price'):self.assertNotIn(key,self.machine.data)
        self.assertEqual(self.machine.data['serial'],'CAT-SN1234')
        self.assertEqual(self.machine.data['power'],'70 kW')
        self.assertNotIn('year',summary['applied_fields'])

    def test_year_requires_exact_serial_and_recognized_manufacturer(self):
        unofficial=self.result({'year':'2020'},scope='exact_serial',urls={'year':'https://marketplace.com/item'})
        self.assertEqual(unofficial['research']['fields'],[])
        summary=self.apply(self.job(self.result({'year':'2020'},scope='exact_serial')))
        self.assertIn('year',summary['applied_fields'])
        self.assertEqual(self.machine.data['year'],2020)
        self.assertEqual(self.machine.provenance['year']['scope'],'exact_serial')
        submission=submit_machine(self.machine,self.owner,True)
        references=public_web_references(submission.version.data)
        self.assertEqual(len(references),1)
        self.assertEqual(references[0]['field'],'year')
        self.assertEqual(str(references[0]['value']),'2020')
        self.assertEqual(references[0]['scope'],'exact_serial')
        self.assertEqual(references[0]['source_url'],'https://www.cat.com/equipment/420f2.html')

    def test_web_specification_cannot_embed_a_private_serial_in_its_value(self):
        summary=self.apply(self.job(self.result({'power':'70 kW CAT-SN1234'},scope='exact_serial')))
        self.assertNotIn('power',self.machine.data)
        self.assertNotIn('power',summary['applied_fields'])
        self.assertNotIn('CAT-SN1234',self.machine.data.get('description',''))

    def test_human_edit_is_preserved_and_description_uses_only_accepted_values(self):
        job=self.job(self.result())
        self.machine=save_draft(self.machine,self.owner,{'data':{'power':'64 kW'}},self.machine.revision)
        summary=self.apply(job)
        self.assertEqual(self.machine.data['power'],'64 kW')
        self.assertEqual(self.machine.data['weight'],'8000 kg')
        self.assertIn('64 kW',self.machine.data['description'])
        self.assertNotIn('70 kW',self.machine.data['description'])
        self.assertNotIn('power',summary['applied_fields'])

    def test_changed_or_cleared_identity_blocks_references_during_completion(self):
        for key,value in [('model','OTHER MODEL'),('serial','CORRECTED-SN'),('serial','')]:
            with self.subTest(key=key,value=value):
                self.machine.data={'brand':'Caterpillar','model':'420F2','serial':'CAT-SN1234'}
                self.machine.provenance={};self.machine.save()
                job=self.job(self.result({'power':'70 kW'},scope='exact_serial'))
                self.machine=save_draft(self.machine,self.owner,{'data':{key:value}},self.machine.revision)
                summary=self.apply(job)
                self.assertNotIn('power',self.machine.data)
                self.assertEqual(summary['field_reasons']['power'],'identity_changed')
                self.assertNotIn('70 kW',self.machine.data.get('description',''))

    def test_retry_does_not_reinsert_cleared_value_and_browser_cannot_forge_web_origin(self):
        result=self.result({'power':'70 kW'});job=self.job(result);self.apply(job)
        self.machine=save_draft(self.machine,self.owner,{'data':{'power':''}},self.machine.revision)
        before=self.machine.revision;self.apply(job)
        self.assertEqual(self.machine.data['power'],'')
        self.assertEqual(self.machine.revision,before)
        self.machine=save_draft(self.machine,self.owner,{'data':{'power':'80 kW'},
            'provenance':{'power':result['provenance']['power']}},self.machine.revision)
        self.assertEqual(self.machine.provenance['power']['source'],'user')
        self.assertEqual(self.machine.provenance['power']['review'],'confirmed')
        self.assertTrue(self.machine.provenance['power']['source_date'])
        forged=self.result({'weight':'8000 kg'});forged['research']['proof']='forged'
        with self.assertRaises(ValidationError):
            apply_analysis_suggestions(self.machine,self.owner,self.job(forged),['weight'],self.machine.revision)

    def test_human_cleared_description_is_not_replaced_by_analysis_or_submission(self):
        self.machine=save_draft(self.machine,self.owner,{'data':{'description':''}},self.machine.revision)
        self.apply(self.job(self.result()))
        self.assertEqual(self.machine.data['description'],'')
        submission=submit_machine(self.machine,self.owner,True)
        self.assertEqual(submission.version.data['data']['description'],'')

    def test_sheets_omit_citations_while_export_preserves_safe_references(self):
        safe_url='https://www.cat.com/equipment/420f2.html'
        result=self.result({'power':'70 kW','weight':'8000 kg','capacity':'1.2 m3'},
            urls={'weight':'https://www.cat.com/equipment/CAT%2DSN1234','capacity':'https://www.cat.com/search?serial=OTHER-SERIAL'},
            titles={'weight':'Documento CAT-SN1234'})
        job=self.job(result);self.apply(job)
        set_advertiser_status(self.owner,self.admin,'approved','Prueba')
        submission=submit_machine(self.machine,self.owner,True)
        self.asset.public_authorized=True;self.asset.save()
        record_local_duplicate_review(
            self.machine, submission, self.admin, "no_match",
            "Se revisaron serie, marca, modelo y el activo de la solicitud.",
        )
        review_submission(submission,self.admin,'approved');self.machine.refresh_from_db()
        version=self.machine.approved_version
        publication=set_publication(self.machine,self.admin,True)
        # The published snapshot has its own proof; mutable job data is not read.
        job.result={};job.save(update_fields=['result'])
        references=public_web_references(version.data)
        self.assertEqual(len(references),3)
        self.assertEqual(references[0]['source_url'],safe_url)
        self.assertTrue(all(item['private_source'] for item in references[1:]))
        encoded=json.dumps(references)
        self.assertNotIn('CAT-SN1234',encoded)
        self.assertNotIn('OTHER-SERIAL',encoded)
        self.assertNotIn('proof',encoded)
        response=self.client.get(f'/ficha/{publication.token}/')
        self.assertNotContains(response,safe_url)
        self.assertContains(response,'70 kW')
        self.assertNotContains(response,'CAT-SN1234')
        pdf=build_pdf(self.machine,version.data['data'],[self.asset],True,version)
        reader=PdfReader(BytesIO(pdf));text='\n'.join(page.extract_text() for page in reader.pages)
        self.assertNotIn('Referencia del modelo',text)
        self.assertNotIn('CAT-SN1234',text)
        links=[str(annotation.get_object().get('/A',{}).get('/URI','')) for page in reader.pages for annotation in page.get('/Annots',[])]
        self.assertNotIn(safe_url,links)
        self.assertNotIn('CAT', ''.join(link for link in links if link!=safe_url))
        self.client.force_login(self.admin)
        prepared=self.client.post(f'/operaciones/maquinarias/{self.machine.pk}/exportar/')
        self.assertEqual(prepared.status_code, 302)
        delivery=IntegrationDelivery.objects.get(source_machine_id=self.machine.pk)
        record_manual_review(delivery, self.admin, imc_advertiser='Cuenta IMC de prueba',
                             duplicate_result='no_match',
                             evidence='Se revisaron manualmente los resultados de duplicado para IMC.')
        response=self.client.post(f'/operaciones/maquinarias/{self.machine.pk}/exportar/')
        self.assertEqual(response.status_code,200)
        package=zipfile.ZipFile(BytesIO(response.content))
        exported=json.loads(package.read('publicacion.json'))
        self.assertNotIn('web_references', exported)
        self.assertNotIn('serial',exported['data'])
        self.assertNotIn('CAT-SN1234',json.dumps(exported))

    def test_public_references_reject_tampered_snapshot_manifest(self):
        job=self.job(self.result({'power':'70 kW'}));self.apply(job)
        submission=submit_machine(self.machine,self.owner,True)
        changed=deepcopy(submission.version.data)
        changed['web_research'][str(job.pk)]['fields'][0]['value']='999 kW'
        self.assertEqual(public_web_references(changed),[])
