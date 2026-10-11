"""A prepared serial-only fiche retains AI ranges and owner details end to end."""
from copy import deepcopy
import json
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings

from portal.ai_completion import complete_machine_reference, merge_machine_reference, normalize_reference
from portal.intake import preparation_completeness
from portal.models import AnalysisJob, Category, Consent, Machine, PreparedShare, User
from portal.services import apply_analysis_automatically, automatic_application_snapshot, save_draft
from portal.tests.test_ai_completion import proposal
from portal.valuation import _identity


@override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_URL='https://example.invalid', STORAGES={
    'default': {'BACKEND': 'portal.storage.PrivateStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class AIReferenceApplicationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='complete-fiche@example.invalid', phone='+525512345678')
        self.category = Category.objects.create(name='Excavadoras', slug='excavadoras')
        values = {'brand': 'Caterpillar', 'model': '320D', 'serial': 'CAT0320DTEST123',
                  'hours': 0, 'location_country': 'México', 'location_region': 'Sonora',
                  'location_city': 'Hermosillo'}
        self.machine = Machine.objects.create(owner=self.user, data=values,
            provenance={key: {'source': 'user', 'review': 'confirmed'} for key in values})
        Consent.objects.create(user=self.user, machine=self.machine, kind='ai', granted=True)
        self.client.force_login(self.user)

    def job(self):
        snapshot = {'data': deepcopy(self.machine.data), 'provenance': deepcopy(self.machine.provenance)}
        result = {'data': {}, 'provenance': {}, 'category': None, 'fields': [], 'plates': [],
                  'relevance': {'status': 'unassessed'}, 'completion': {'missing_fields': []}}
        reference = normalize_reference(proposal(), _identity(result, snapshot), self.machine.data,
            self.machine.category.name if self.machine.category_id else None, ['Excavadoras'], [self.machine.data['serial']])
        merge_machine_reference(result, reference, snapshot)
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, mode='description',
            status='completed', auto_apply=True, revision=self.machine.revision, asset_ids=[],
            fingerprint=uuid.uuid4().hex, application_snapshot=automatic_application_snapshot(self.machine), result=result)

    def apply(self, job):
        self.machine, outcome = apply_analysis_automatically(self.machine, self.user, job, self.machine.revision)
        return outcome

    def edit(self, **values):
        self.machine = save_draft(self.machine, self.user, {'data': values}, self.machine.revision)

    def test_serial_only_fills_type_both_ranges_and_summary_preserving_owner_details(self):
        job = self.job()
        outcome = self.apply(job)
        self.assertEqual(outcome['status'], 'applied')
        self.assertEqual(self.machine.category_id, self.category.pk)
        self.assertEqual(self.machine.data['estimate_min'], 45000)
        self.assertEqual(self.machine.data['estimated_year_from'], 2006)
        self.assertEqual(len(self.machine.data['description'].splitlines()), 4)
        self.assertEqual(self.machine.data['hours'], 0)
        self.assertEqual(self.machine.data['location_city'], 'Hermosillo')
        self.assertNotIn('price', self.machine.data)
        self.assertEqual(preparation_completeness(self.machine, job)['missing_fields'], [])
        preview = self.client.get(f'/panel/maquinarias/{self.machine.pk}/ficha/')
        self.assertContains(preview, 'Rango de precio estimado')
        self.assertContains(preview, 'Rango de año estimado')
        self.assertContains(preview, 'Hermosillo')
        response = self.client.post(f'/api/maquinarias/{self.machine.pk}/compartir/',
            json.dumps({'revision': self.machine.revision, 'include_serial': True}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        share = PreparedShare.objects.get()
        page = Client().get(f'/s/{share.code}/')
        self.assertContains(page, self.machine.data['serial'])
        self.assertContains(page, 'Hermosillo')
        self.assertContains(page, 'Sonora')
        self.assertContains(page, 'México')
        self.assertNotContains(page, 'Pendiente')
        self.assertEqual(page.context['data']['hours'], 0)
        self.assertEqual(page.context['data']['estimate_min'], 45000)
        self.assertEqual(page.context['data']['estimated_year_to'], 2015)

    def test_known_unit_year_satisfies_year_data_without_suppressing_price_reference(self):
        self.edit(year=2010, price='65000', currency='USD')
        self.apply(self.job())
        self.assertEqual(self.machine.data['year'], 2010)
        self.assertEqual(self.machine.data['price'], 65000)
        self.assertNotIn('estimated_year_from', self.machine.data)
        self.assertEqual(self.machine.data['estimate_max'], 90000)
        self.assertEqual(preparation_completeness(self.machine)['missing_fields'], [])

    def test_concurrent_owner_range_and_description_edits_win(self):
        job = self.job()
        self.edit(estimate_min='60000', estimate_max='80000', estimate_currency='USD', description='Descripción del propietario.')
        self.apply(job)
        self.assertEqual(self.machine.data['estimate_min'], 60000)
        self.assertEqual(self.machine.data['description'], 'Descripción del propietario.')
        self.assertEqual(self.machine.provenance['description']['source'], 'user')

    def test_owner_identity_edit_retires_estimates_but_can_share_remaining_data(self):
        self.apply(self.job())
        self.edit(model='320DL')
        self.assertNotIn('estimate_min', self.machine.data)
        self.assertNotIn('estimated_year_from', self.machine.data)
        response = self.client.post(f'/api/maquinarias/{self.machine.pk}/compartir/',
            json.dumps({'revision': self.machine.revision}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        shared = PreparedShare.objects.get().snapshot['data']
        self.assertEqual(shared['model'], '320DL')
        self.assertNotIn('estimate_min', shared)
        self.assertNotIn('estimated_year_from', shared)

    def test_forged_manifest_never_applies_ranges(self):
        job = self.job()
        job.result['ai_reference']['fields']['estimate_min'] = '1'
        job.save(update_fields=['result'])
        self.apply(job)
        self.assertNotIn('estimate_min', self.machine.data)
        self.assertNotIn('estimated_year_from', self.machine.data)

    def test_existing_catalogue_specs_do_not_discard_generated_price_and_description(self):
        self.machine.category = self.category
        for key, value in {'power': '41.7 kW', 'weight': '7150 kg', 'digging_depth': '4110 mm'}.items():
            self.machine.data[key] = value
            self.machine.provenance[key] = {'source': 'web_model', 'review': 'needs_review', 'basis': 'catalogue_intake'}
        self.machine.save()
        job = self.job()
        result = {'data': {}, 'provenance': {}, 'category': self.category.name, 'fields': [], 'plates': []}
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status='completed', output_parsed=proposal(),
            usage=SimpleNamespace(input_tokens=100, output_tokens=100))
        snapshot = {'data': deepcopy(self.machine.data), 'provenance': deepcopy(self.machine.provenance)}
        reference, _ = complete_machine_reference(client, 'gpt-6-luna', result, snapshot,
            allowed_categories=[self.category.name])
        self.assertEqual(reference['identity']['technical_context']['weight'], '7150 kg')
        # Snapshot context prevents stale application; it does not promote an
        # unvalidated draft specification into provider-accepted evidence.
        payload = json.loads(client.responses.parse.call_args.kwargs['input'])
        self.assertNotIn('weight', payload['accepted_data'])
        merge_machine_reference(result, reference, snapshot)
        job.result = result
        job.save(update_fields=['result'])
        self.apply(job)
        self.assertEqual(self.machine.data['estimate_min'], 45000)
        self.assertEqual(self.machine.data['estimate_max'], 90000)
        self.assertEqual(len(self.machine.data['description'].splitlines()), 4)
        self.edit(weight='8000 kg')
        self.assertNotIn('estimate_min', self.machine.data)
