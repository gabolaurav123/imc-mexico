"""Regression coverage for the category-to-approved-snapshot workflow; no remote calls."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from portal.analysis_specialization import check_equipment_consistency
from portal.models import AnalysisJob, Asset, Category, Machine, PlatformSettings, User
from portal.processing import normalize_analysis, enqueue_analysis, process_next_job
from portal.services import save_draft, snapshot, apply_analysis_suggestions
from portal.tests.test_image_relevance import field, observation, parsed


class EquipmentConsistencyTests(SimpleTestCase):
    def test_different_machine_identifiers_require_separate_listings(self):
        result = normalize_analysis(parsed([
            observation('a', category='Excavadoras'), observation('b', category='Excavadoras')],
            [field('model', '320', 'a'), field('model', 'PC200', 'b')]),
            ['a', 'b'], allowed_categories=['Excavadoras'])
        self.assertEqual(check_equipment_consistency(result), 'multiple_machines')
        self.assertEqual(set(result['multiple_machines']['asset_ids']), {'a', 'b'})

    def test_component_identifiers_and_brand_aliases_do_not_mean_different_units(self):
        engine = field('model', 'C7.1', 'b', 'plate'); engine['component'] = 'engine'
        result = {'fields': [field('brand', 'CAT', 'a'), field('brand', 'Caterpillar', 'b'),
                             field('model', '320', 'a'), engine], 'image_observations': []}
        self.assertFalse(check_equipment_consistency(result))

    def test_selected_category_is_not_silently_replaced(self):
        result = {'category': 'Montacargas', 'fields': [], 'image_observations': []}
        self.assertEqual(check_equipment_consistency(result, {'category': 'Excavadoras'}), 'category_conflict')
        self.assertEqual(result['category_conflict']['selected'], 'Excavadoras')

    def test_hour_estimates_from_wear_are_rejected(self):
        proposal = field('hours', '5000', 'a'); proposal['evidence'] = 'Horas estimadas por desgaste'
        result = normalize_analysis(parsed([observation('a', category='Excavadoras')], [proposal]),
                                    ['a'], allowed_categories=['Excavadoras'])
        self.assertIsNone(result['data']['hours'])


@override_settings(OPENAI_API_KEY='test-only', OPENAI_MODEL='gpt-4.1-mini', OPENAI_VISION_MODEL='gpt-4.1-mini',
                   SECURE_SSL_REDIRECT=False, STORAGES={
                       'default': {'BACKEND':'portal.storage.PrivateStorage'},
                       'staticfiles': {'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ExcavatorIntegrationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='excavator-test@example.invalid')
        self.category = Category.objects.create(name='Excavadoras', slug='excavadoras')
        self.machine = Machine.objects.create(owner=self.owner, category=self.category,
            provenance={'category': {'source':'user','review':'confirmed'}})
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=1000000)
        self.asset = self.photo('a')

    def photo(self, char, purpose='general'):
        return Asset.objects.create(machine=self.machine, kind='image', purpose=purpose,
            processing_status='ready', original='test/unused.jpg', preview='test/unused.jpg',
            size=1, mime_type='image/jpeg', sha256=char*64)

    def response(self, category='Excavadoras', count=1):
        return SimpleNamespace(status='completed', output_parsed=parsed([
            observation('image_001', category=category, machine_count=count)],
            [field('brand','Caterpillar','image_001'),field('model','320','image_001')]),
            usage=SimpleNamespace(input_tokens=300, output_tokens=100))

    def run_job(self, response=None, research=False):
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True, research=research,
                               auto_apply=True, expected_revision=self.machine.revision)
        with patch('portal.processing._image_input', return_value={'type':'input_image','image_url':'data:test'}), \
             patch('openai.OpenAI') as provider, patch('portal.processing.research_machine') as external:
            provider.return_value.responses.parse.return_value = response or self.response()
            self.assertTrue(process_next_job())
        self.machine.refresh_from_db(); job.refresh_from_db()
        return job, provider.return_value.responses.parse.call_count, external

    def test_adding_plate_reuses_previous_photo_and_keeps_human_correction(self):
        first, calls, _ = self.run_job()
        self.assertEqual(first.status, 'completed'); self.assertEqual(calls, 1)
        self.photo('b', 'plate')
        self.machine.revision += 1; self.machine.save(update_fields=['revision'])
        second, calls, _ = self.run_job()
        self.assertEqual(second.status, 'completed'); self.assertEqual(calls, 1)
        self.assertCountEqual([row['status'] for row in second.result['image_readings']], ['reused','completed'])
        self.assertEqual(second.input_tokens, 300)
        self.assertEqual(self.machine.category_id, self.category.pk)

    def test_multiple_units_never_autofill_or_trigger_paid_research(self):
        job, calls, external = self.run_job(self.response(count=2), research=True)
        self.assertEqual(job.result['blocking_reason'], 'multiple_machines')
        external.assert_not_called()
        self.assertFalse(self.machine.data)
        self.assertEqual(job.application_result['reason'], 'multiple_machines')

    def test_snapshot_indexes_numeric_values_from_immutable_data(self):
        saved = save_draft(self.machine, self.owner, {'data':{'hours':'0','year':'2018',
            'weight':'21.5 t','digging_depth':'670 cm','price':'123456.50','currency':'MXN',
            'location_country':'México','location_city':'Monterrey','undercarriage':'crawler'}}, 1)
        version = snapshot(saved,self.owner)
        self.assertEqual(version.hours, 0)
        self.assertEqual(version.weight_kg, 21500)
        self.assertEqual(version.digging_depth_m, __import__('decimal').Decimal('6.70'))
        self.assertEqual(version.data['structured']['weight_kg'], 21500)
        self.assertEqual(saved.data['hours_basis'], 'owner_declared')
        self.assertTrue(saved.data['hours_recorded_at'])
        save_draft(saved,self.owner,{'data':{'price':'500','hours':'200'}},saved.revision)
        version.refresh_from_db()
        self.assertEqual(float(version.price),123456.5)
        self.assertEqual(version.hours,0)

    def test_unknown_numeric_is_null_and_ambiguous_number_is_rejected(self):
        saved = save_draft(self.machine,self.owner,{'data':{'hours':'','year':'N/A'}},1)
        self.assertIsNone(saved.data['hours']); self.assertIsNone(saved.data['year'])
        with self.assertRaises(ValidationError):
            save_draft(saved,self.owner,{'data':{'hours':'1,500'}},saved.revision)

    def test_batch_conflicts_apply_after_automatic_save_but_not_after_manual_edit(self):
        job, _, _ = self.run_job()
        applied = apply_analysis_suggestions(self.machine,self.owner,job,['brand'],self.machine.revision)
        self.assertEqual(applied.provenance['brand']['review'],'confirmed')
        with self.assertRaises(ValidationError):
            apply_analysis_suggestions(applied,self.owner,job,['model'],applied.revision)

    def test_category_choice_starts_without_plate_or_paid_work(self):
        self.client.force_login(self.owner)
        response = self.client.get('/panel/maquinarias/nueva/')
        self.assertContains(response, '¿Qué tipo de máquina quieres anunciar?')
        self.assertContains(response, 'No estoy seguro')
        response = self.client.post('/api/maquinarias/', {'category': self.category.pk}, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        created = Machine.objects.get(pk=response.json()['id'])
        self.assertEqual(created.category_id,self.category.pk)
        self.assertEqual(created.provenance['category']['source'],'user')
        self.assertFalse(created.assets.exists())
        self.assertFalse(AnalysisJob.objects.exists())
        unknown = self.client.post('/api/maquinarias/', {'category':'unsure'}, content_type='application/json')
        self.assertEqual(unknown.status_code,201)
        self.assertIsNone(Machine.objects.get(pk=unknown.json()['id']).category_id)
