"""Paver-specific retrieval and serial enrichment, using synthetic evidence only."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

from django.test import SimpleTestCase, TestCase

from portal.category_profiles import category_catalog, profile_for_category
from portal.models import AnalysisJob, Asset, Category, Consent, Machine, User
from portal.research import (WEB_KEYS, ResearchExtraction, ResearchField, merge_research,
                             normalize_research, research_machine)
from portal.research_pipeline import _stage_request
from portal.services import (AUTOMATIC_DATA_FIELDS, DATA_FIELDS, apply_analysis_automatically,
                             automatic_application_snapshot, save_draft)
from portal.tests.test_research import web_response


class PaverProfileTests(SimpleTestCase):
    def test_profile_exposes_supported_fields_and_both_paving_families(self):
        profile = profile_for_category('pavimentadoras')
        keys = {item['key'] for item in profile['fields']}
        self.assertEqual(profile['key'], 'paver')
        self.assertTrue({'working_width', 'weight', 'power', 'capacity', 'engine'} <= keys)
        self.assertTrue(keys <= DATA_FIELDS)
        self.assertTrue(keys <= AUTOMATIC_DATA_FIELDS)
        self.assertTrue(keys - {'variant', 'undercarriage'} <= WEB_KEYS)
        self.assertIn('pavimentadora de concreto', profile['aliases'])
        self.assertIn('asfalto', profile['ai_instructions'])
        self.assertIn('concreto', profile['ai_instructions'])
        self.assertTrue(profile['photo_guidance'])

    def test_live_category_payload_keeps_legacy_fields_and_adds_photo_guidance(self):
        category = SimpleNamespace(pk=42, slug='pavimentadoras', name='Pavimentadoras',
                                   active=True, fields=['power', 'weight', 'dimensions', 'engine'])
        record = category_catalog([category])[0]
        self.assertEqual(record['fields'], category.fields)
        self.assertEqual(record['profile']['key'], 'paver')
        self.assertIn('asphalt paver', record['aliases'])
        self.assertIn('concrete slipform paver', record['aliases'])
        self.assertIn('working_width', {item['key'] for item in record['profile']['fields']})

    def test_paver_guidance_never_leaks_into_other_categories(self):
        profile = profile_for_category('pavimentadoras')
        profile['fields'].clear()
        self.assertTrue(profile_for_category('pavimentadoras')['fields'])
        other = profile_for_category('compactadores')
        self.assertEqual(other['key'], 'compactor')
        request, _ = _stage_request({'brand': 'Caterpillar', 'model': 'TEST-COMPACTOR', 'serial': None},
                                   'manufacturer', {'data': {}}, 'Compactadores')
        self.assertNotIn('paver', request['query'])
        self.assertNotIn('tolva', request['objective'])

    def test_serial_query_keeps_unit_and_model_stages_drop_serial(self):
        identity = {'serial': 'PAVER-TEST-123', 'brand': 'Caterpillar', 'model': 'TEST-PAVER'}
        for stage in ('serial', 'manufacturer', 'catalogs', 'manuals'):
            with self.subTest(stage=stage):
                request, _ = _stage_request(identity, stage, {'data': {}}, 'Pavimentadoras')
                self.assertIn('pavimentadora paver', request['query'])
                self.assertIn('working_width', request['priority_missing_fields'])
                self.assertIn('ancho básico', request['objective'])
                self.assertIn('concreto', request['objective'])
                self.assertIn('nunca depósito de combustible', request['objective'])
                if stage == 'serial':
                    self.assertIn('PAVER-TEST-123', request['query'])
                else:
                    self.assertIsNone(request['identifiers']['serial'])
                    self.assertNotIn('PAVER-TEST-123', request['query'])

    def test_new_owner_serial_is_researched_with_existing_photo_identity(self):
        result = {'data': {'brand': 'Caterpillar', 'model': 'TEST-PAVER'},
                  'provenance': {key: {'source': 'image', 'review': 'clear', 'component': 'machine',
                                       'asset_id': 'photo-test'} for key in ('brand', 'model')},
                  'fields': [], 'plates': [], 'warnings': [], 'category': 'Pavimentadoras'}
        snapshot = {'data': {'serial': 'PAVER-TEST-123'}, 'category': 'Pavimentadoras',
                    'provenance': {'serial': {'source': 'user', 'review': 'confirmed'},
                                   'category': {'source': 'user', 'review': 'confirmed'}}}
        client = Mock()
        client.responses.create.return_value = web_response(sources=[])
        research, _ = research_machine(client, 'gpt-6-luna', result, snapshot,
                                       allowed_categories=['Pavimentadoras'])
        requests = [json.loads(call.kwargs['input']) for call in client.responses.create.call_args_list]
        self.assertEqual([request['research_stage'] for request in requests], ['serial', 'manufacturer', 'catalogs'])
        self.assertEqual(requests[0]['identifiers'], {
            'brand': 'Caterpillar', 'model': 'TEST-PAVER', 'serial': 'PAVER-TEST-123'})
        self.assertTrue(all('pavimentadora paver' in request['query'] for request in requests))
        self.assertEqual(research['fields'], [])  # No evidence cannot manufacture specifications.


class PaverSerialAutofillTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='paver-regression@example.invalid', is_test=True)
        self.category = Category.objects.create(name='Pavimentadoras', slug='pavimentadoras')
        self.machine = Machine.objects.create(owner=self.owner, category=self.category,
            data={'brand': 'Caterpillar', 'model': 'TEST-PAVER'})
        self.asset = Asset.objects.create(machine=self.machine, kind='image', purpose='general',
            processing_status='ready', original='tests/paver.jpg', preview='tests/paver-preview.jpg',
            sha256='a' * 64, size=1, mime_type='image/jpeg')
        self.machine.provenance = {key: {'source': 'image', 'review': 'clear', 'component': 'machine',
                                         'asset_id': str(self.asset.pk)} for key in ('brand', 'model')}
        self.machine.save(update_fields=['provenance'])
        Consent.objects.create(user=self.owner, machine=self.machine, kind='ai', granted=True)

    def test_new_serial_research_fills_technical_fields_preserving_owner_corrections(self):
        # This is the second analysis: photographs already identified the model,
        # then the owner added a serial and exact commercial details.
        corrections = {'serial': 'PAVER-TEST-123', 'year': 2017, 'price': 120000,
                       'currency': 'USD', 'hours': 2345, 'description': 'Descripción del propietario.'}
        self.machine = save_draft(self.machine, self.owner, {'data': corrections}, self.machine.revision)
        snapshot = automatic_application_snapshot(self.machine)
        identity = {key: self.machine.data[key] for key in ('brand', 'model', 'serial')}
        url = 'https://www.cat.com/qa-synthetic-paver-evidence'
        fields = []
        passages = []
        for key, value in {'working_width': '3.0 m', 'power': '90 kW', 'year': '2018'}.items():
            passage = f'Caterpillar TEST-PAVER, serial PAVER-TEST-123: {key} {value}.'
            fields.append(ResearchField(key=key, value=value, scope='exact_serial', source_url=url,
                evidence=passage, matched_brand=identity['brand'], matched_model=identity['model'],
                matched_serial=identity['serial']))
            passages.append(passage)
        research = normalize_research(ResearchExtraction(fields=fields), identity, 'exact_serial',
            [{'url': url, 'title': 'Synthetic paver test evidence'}], '\n\n'.join(passages),
            citations={url: passages})
        result = merge_research({'data': {}, 'provenance': {}, 'fields': [], 'plates': [], 'warnings': [],
            'category': 'Pavimentadoras', 'relevance': {'status': 'machinery'}}, research)
        job = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, mode='analysis',
            revision=self.machine.revision, asset_ids=[str(self.asset.pk)], fingerprint=uuid.uuid4().hex,
            status='completed', auto_apply=True, application_snapshot=deepcopy(snapshot), result=result)
        self.machine, outcome = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        self.assertEqual(outcome['status'], 'applied')
        self.assertEqual(self.machine.data['working_width'], '3.0 m')
        self.assertEqual(self.machine.data['power'], '90 kW')
        for key, value in corrections.items():
            self.assertEqual(self.machine.data[key], value)
        self.assertNotIn('year', outcome['applied_fields'])
        self.assertEqual(self.machine.provenance['working_width']['scope'], 'exact_serial')
        self.assertEqual(self.machine.provenance['serial']['source'], 'user')
