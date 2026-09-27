"""Model references survive owner details while real corrections remain binding."""
from copy import deepcopy
import json
import uuid

from django.test import Client, TestCase, override_settings

from portal.ai_completion import (PREVIOUS_PRICE_LABEL, PREVIOUS_PRICE_NOTE,
    merge_machine_reference, normalize_reference)
from portal.intake import preparation_completeness
from portal.models import AnalysisJob, Category, Consent, Machine, PreparedShare, User
from portal.services import (apply_analysis_automatically, automatic_application_snapshot,
                             machine_valuation, save_draft)
from portal.tests.test_ai_completion import proposal
from portal.valuation import LABEL, VALUATION_VERSION, _identity, _seal


@override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_URL='https://example.invalid', STORAGES={
    'default': {'BACKEND': 'portal.storage.PrivateStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class AIReferenceContextTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='reference-context@example.invalid')
        self.category = Category.objects.create(name='Excavadoras', slug='excavadoras')
        data = {'brand': 'Caterpillar', 'model': '320D', 'serial': 'QA-CONTEXT-123'}
        self.machine = Machine.objects.create(owner=self.user, category=self.category, data=data,
            provenance={key: {'source': 'user', 'review': 'confirmed'} for key in data})
        Consent.objects.create(user=self.user, machine=self.machine, kind='ai', granted=True)
        self.client.force_login(self.user)

    def job(self, **changes):
        snapshot = {'data': deepcopy(self.machine.data), 'provenance': deepcopy(self.machine.provenance)}
        result = {'data': {}, 'provenance': {}, 'category': 'Excavadoras', 'fields': [], 'plates': [],
                  'relevance': {'status': 'unassessed'}, 'input_snapshot': snapshot,
                  'completion': {'missing_fields': []}}
        reference = normalize_reference(proposal(**changes), _identity(result, snapshot), self.machine.data,
            'Excavadoras', ['Excavadoras'], [self.machine.data['serial']])
        merge_machine_reference(result, reference, snapshot)
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, mode='description',
            status='completed', auto_apply=True, revision=self.machine.revision, asset_ids=[],
            fingerprint=uuid.uuid4().hex, application_snapshot=automatic_application_snapshot(self.machine), result=result)

    def apply(self, job):
        self.machine, outcome = apply_analysis_automatically(self.machine, self.user, job, self.machine.revision)
        return outcome

    def edit(self, **values):
        self.machine = save_draft(self.machine, self.user, {'data': values}, self.machine.revision)

    def valuation_job(self):
        self.edit(condition='Usada')
        snapshot = {'data': deepcopy(self.machine.data), 'provenance': deepcopy(self.machine.provenance)}
        fields = {'estimate_min': '45000', 'estimate_max': '90000', 'estimate_currency': 'USD',
                  'estimate_market': 'Estados Unidos', 'estimate_date': '2026-09-18',
                  'estimate_basis': 'Comparables públicos del mismo modelo.'}
        valuation = _seal({'version': VALUATION_VERSION, 'label': LABEL, 'status': 'estimated',
            'identity': _identity({}, snapshot), 'fields': fields, 'suggested_price': '60000', 'comparables': []})
        result = {'valuation': valuation, 'data': {**fields, 'estimate_suggested_price': '60000'},
                  'category': 'Excavadoras', 'relevance': {'status': 'unassessed'},
                  'research': {'status': 'no_results'}}
        result['provenance'] = {key: {'source': 'valuation', 'review': 'needs_review', 'component': 'machine'}
                                for key in result['data']}
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, mode='description',
            status='completed', auto_apply=True, revision=self.machine.revision, asset_ids=[],
            fingerprint=uuid.uuid4().hex, application_snapshot=automatic_application_snapshot(self.machine), result=result)

    def test_hours_and_country_keep_summary_and_ranges_with_original_market_and_date(self):
        job = self.job()
        self.apply(job)
        original = deepcopy(self.machine.data)
        self.edit(hours=0, location_country='México', location_region='Sonora', location_city='Hermosillo')
        self.machine.refresh_from_db()
        for key in ('brand', 'model', 'description', 'estimated_year_from', 'estimated_year_to',
                    'estimate_min', 'estimate_max', 'estimate_currency', 'estimate_market', 'estimate_date'):
            self.assertEqual(self.machine.data[key], original[key], key)
        self.assertEqual(self.machine.data['estimate_market'], 'Estados Unidos')
        self.assertEqual(self.machine.data['hours'], 0)
        self.assertEqual(self.machine.provenance['hours']['source'], 'user')
        self.assertEqual(self.machine.provenance['estimate_min']['label'], PREVIOUS_PRICE_LABEL)
        self.assertIn(PREVIOUS_PRICE_NOTE, self.machine.data['estimate_basis'])
        self.assertEqual(preparation_completeness(self.machine, job)['missing_fields'], [])
        response = self.client.post(f'/api/maquinarias/{self.machine.pk}/compartir/',
            json.dumps({'revision': self.machine.revision}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        public = Client().get(f'/s/{PreparedShare.objects.get().code}/')
        self.assertContains(public, 'Rango de precio estimado')
        self.assertContains(public, 'Hermosillo')
        self.assertContains(public, 'Superestructura giratoria')

    def test_concurrent_owner_details_do_not_discard_job_reference(self):
        job = self.job()
        self.edit(hours=2418, location_country='México', year=2010)
        self.apply(job)
        self.assertEqual(self.machine.data['hours'], 2418)
        self.assertEqual(self.machine.data['year'], 2010)
        self.assertEqual(self.machine.data['estimate_min'], 45000)
        self.assertNotIn('estimated_year_from', self.machine.data)
        self.assertEqual(self.machine.data['description'], job.result['data']['description'])
        self.assertEqual(self.machine.provenance['estimate_min']['label'], PREVIOUS_PRICE_LABEL)

    def test_exact_year_retires_contradictory_automatic_period_but_keeps_sheet_complete(self):
        job = self.job(year_from=2008, year_to=2016)
        self.apply(job)
        description = self.machine.data['description']
        self.edit(year=2001)
        self.machine.refresh_from_db()
        for key in ('estimated_year_from', 'estimated_year_to', 'estimated_year_basis'):
            self.assertNotIn(key, self.machine.data)
            self.assertNotIn(key, self.machine.provenance)
        self.assertEqual(self.machine.data['year'], 2001)
        self.assertEqual(self.machine.data['description'], description)
        self.assertEqual(self.machine.data['estimate_min'], 45000)
        self.assertEqual(self.machine.provenance['estimate_min']['label'], PREVIOUS_PRICE_LABEL)
        self.assertEqual(preparation_completeness(self.machine, job)['missing_fields'], [])
        preview = self.client.get(f'/panel/maquinarias/{self.machine.pk}/ficha/')
        self.assertContains(preview, '2001')
        self.assertNotContains(preview, 'Rango de año estimado')

    def test_exact_year_added_during_analysis_rejects_old_period_without_rejecting_summary_or_price(self):
        job = self.job(year_from=2008, year_to=2016)
        self.edit(year=2001)
        outcome = self.apply(job)
        for key in ('estimated_year_from', 'estimated_year_to', 'estimated_year_basis'):
            self.assertNotIn(key, self.machine.data)
            self.assertEqual(outcome['field_reasons'][key], 'known_year')
        self.assertEqual(self.machine.data['year'], 2001)
        self.assertEqual(self.machine.data['description'], job.result['data']['description'])
        self.assertEqual(self.machine.data['estimate_min'], 45000)
        self.assertEqual(preparation_completeness(self.machine, job)['missing_fields'], [])

    def test_exact_year_does_not_erase_an_explicit_owner_period(self):
        self.apply(self.job())
        self.edit(estimated_year_from=2008, estimated_year_to=2016,
                  estimated_year_basis='Periodo indicado por el propietario.')
        self.edit(year=2001)
        self.assertEqual(self.machine.data['year'], 2001)
        self.assertEqual(self.machine.data['estimated_year_from'], 2008)
        self.assertEqual(self.machine.data['estimated_year_to'], 2016)
        self.assertEqual(self.machine.data['estimated_year_basis'], 'Periodo indicado por el propietario.')
        self.assertEqual(self.machine.provenance['estimated_year_from']['source'], 'user')

    def test_exact_year_preserves_an_unchanged_ai_period_confirmed_by_owner(self):
        self.apply(self.job(year_from=2008, year_to=2016))
        keys = ('estimated_year_from', 'estimated_year_to', 'estimated_year_basis')
        self.machine = save_draft(self.machine, self.user, {'provenance': {
            key: {'source': 'user', 'review': 'confirmed'} for key in keys}}, self.machine.revision)
        self.edit(year=2001)
        self.assertEqual(self.machine.data['estimated_year_from'], 2008)
        self.assertEqual(self.machine.data['estimated_year_to'], 2016)
        for key in keys:
            self.assertEqual(self.machine.provenance[key]['review'], 'confirmed')

    def test_note_is_idempotent_and_reverting_context_restores_original_reference(self):
        self.apply(self.job())
        basis = self.machine.data['estimate_basis']
        self.edit(hours=100, location_country='México')
        self.edit(hours=200)
        self.assertEqual(self.machine.data['estimate_basis'].count(PREVIOUS_PRICE_NOTE), 1)
        self.edit(hours=None, location_country=None)
        self.assertEqual(self.machine.data['estimate_basis'], basis)
        self.assertNotIn('label', self.machine.provenance['estimate_min'])

    def test_condition_correction_retires_price_but_keeps_model_years_and_technical_summary(self):
        self.apply(self.job())
        description = self.machine.data['description']
        self.edit(operating_status='No funciona (declarado por el propietario)')
        self.assertNotIn('estimate_min', self.machine.data)
        self.assertNotIn('estimate_basis', self.machine.data)
        self.assertEqual(self.machine.data['description'], description)
        self.assertEqual(self.machine.data['estimated_year_from'], 2006)
        self.assertEqual(self.machine.data['model'], '320D')

    def test_technical_correction_replaces_stale_summary_and_preserves_human_value(self):
        self.edit(power='100 kW')
        job = self.job(technical_lines=['Potencia de referencia: 100 kW.',
            'Pluma y brazo articulados para excavación.', 'Superestructura giratoria sobre orugas.'])
        self.apply(job)
        self.assertIn('100 kW', self.machine.data['description'])
        self.edit(power='90 kW')
        self.assertNotIn('100 kW', self.machine.data['description'])
        self.assertIn('90 kW', self.machine.data['description'])
        self.assertEqual(self.machine.provenance['description']['source'], 'system')
        self.assertEqual(self.machine.data['power'], '90 kW')
        self.assertNotIn('estimate_min', self.machine.data)
        self.assertEqual(self.machine.data['estimated_year_from'], 2006)

    def test_concurrent_technical_correction_does_not_apply_old_numeric_summary(self):
        self.edit(power='100 kW')
        job = self.job(technical_lines=['Potencia de referencia: 100 kW.',
            'Pluma y brazo articulados para excavación.', 'Superestructura giratoria sobre orugas.'])
        self.edit(power='90 kW')
        self.apply(job)
        self.assertNotIn('100 kW', self.machine.data['description'])
        self.assertIn('90 kW', self.machine.data['description'])
        self.assertNotIn('estimate_min', self.machine.data)

    def test_serial_change_retires_all_model_proposals_even_with_same_model(self):
        self.apply(self.job())
        self.edit(serial='QA-DIFFERENT-456')
        self.assertNotIn('estimate_min', self.machine.data)
        self.assertNotIn('estimated_year_from', self.machine.data)
        self.assertNotEqual(self.machine.provenance['description']['source'], 'ai_reference')
        self.assertEqual(self.machine.data['serial'], 'QA-DIFFERENT-456')

    def test_human_range_and_summary_are_not_relabelled_or_discarded(self):
        self.apply(self.job())
        self.edit(estimate_min=60000, estimate_max=80000, estimate_currency='MXN',
                  estimate_basis='Referencia propia del propietario.', description='Descripción propia.')
        self.edit(hours=100, location_country='México', model='320DL')
        self.assertEqual(self.machine.data['estimate_min'], 60000)
        self.assertEqual(self.machine.data['estimate_currency'], 'MXN')
        self.assertEqual(self.machine.data['estimate_basis'], 'Referencia propia del propietario.')
        self.assertEqual(self.machine.data['description'], 'Descripción propia.')
        self.assertNotIn('label', self.machine.provenance['estimate_min'])

    def test_verified_valuation_retains_original_range_after_owner_hours_and_country(self):
        self.apply(self.valuation_job())
        description = self.machine.data['description']
        self.edit(hours=0, location_country='México')
        self.assertEqual(self.machine.data['estimate_min'], 45000)
        self.assertEqual(self.machine.data['estimate_max'], 90000)
        self.assertEqual(self.machine.data['estimate_market'], 'Estados Unidos')
        self.assertEqual(self.machine.data['estimate_date'], '2026-09-18')
        self.assertEqual(self.machine.data['description'], description)
        self.assertEqual(self.machine.provenance['estimate_min']['label'], PREVIOUS_PRICE_LABEL)
        self.assertIn(PREVIOUS_PRICE_NOTE, self.machine.data['estimate_basis'])
        self.assertNotIn('estimate_suggested_price', self.machine.data)
        self.assertEqual(machine_valuation(self.machine), {})

    def test_verified_valuation_hours_addition_alone_is_not_a_current_valuation(self):
        self.apply(self.valuation_job())
        self.edit(hours=100)
        self.assertEqual(self.machine.data['estimate_min'], 45000)
        self.assertEqual(self.machine.provenance['estimate_min']['label'], PREVIOUS_PRICE_LABEL)
        self.assertEqual(machine_valuation(self.machine), {})

    def test_previous_verified_valuation_still_expires_after_condition_or_identity_correction(self):
        self.apply(self.valuation_job())
        self.edit(hours=100, location_country='México')
        self.edit(condition='Para reparación')
        self.assertNotIn('estimate_min', self.machine.data)
        self.edit(condition='Usada')
        self.apply(self.valuation_job())
        self.edit(model='320DL')
        self.assertNotIn('estimate_min', self.machine.data)

    def test_previous_verified_valuation_cannot_survive_configuration_correction(self):
        self.edit(engine='Motor de referencia')
        self.apply(self.valuation_job())
        self.edit(hours=100)
        self.edit(engine='Motor corregido')
        self.assertNotIn('estimate_min', self.machine.data)
