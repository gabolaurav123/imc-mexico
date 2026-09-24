"""Regression coverage for the category-to-approved-snapshot workflow; no remote calls."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from portal.analysis_specialization import check_equipment_consistency
from portal.models import AnalysisJob, Asset, Category, Machine, PlatformSettings, User
from portal.processing import (_merge_image_results, _photo_cache_keys, _preserve_repeated_ambiguous_model,
                               normalize_analysis, enqueue_analysis, process_next_job)
from portal.research import research_identity
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

    def test_same_general_photo_cannot_promote_a_previous_doubtful_model_on_v37(self):
        asset_id = str(self.asset.pk)

        def reading(value, review):
            return {"data": {"model": value}, "provenance": {"model": {
                "source": "image", "review": review, "component": "machine", "asset_id": asset_id}},
                "fields": [{"key": "model", "label": "Modelo", "value": value, "source": "image", "review": review,
                            "component": "machine", "asset_id": asset_id, "evidence": value}],
                "relevance": {"status": "relevant", "accepted_asset_ids": [asset_id]},
                "image_observations": [{"asset_id": asset_id, "kind": "machine", "relevance": "machinery"}],
                "plates": [], "warnings": [], "questions": []}

        prior = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, revision=self.machine.revision,
            asset_ids=[asset_id], fingerprint="prior-" + uuid4().hex, status="completed", prompt_version="imc-excavators-2026-09-v36",
            result={"input_snapshot": {}, "photo_cache": []})
        # This is the v36 cache shape: the key itself binds asset id, SHA and
        # purpose, but did not yet persist those parts beside the reading.
        prior.result["photo_cache"] = [{"key": _photo_cache_keys(prior, [self.asset], {})[asset_id],
                                        "reading": reading("320D", "needs_review")}]
        prior.save(update_fields=["result"])
        current = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, revision=self.machine.revision,
            asset_ids=[asset_id], fingerprint="current-" + uuid4().hex, status="queued")

        repeated = reading("320D", "clear")
        self.assertTrue(_preserve_repeated_ambiguous_model(current, self.asset, {}, repeated))
        self.assertEqual(repeated["provenance"]["model"]["review"], "needs_review")
        self.assertEqual(repeated["fields"][0]["review"], "needs_review")

        plate = self.photo("p", "plate")
        plate_id = str(plate.pk)
        plate_reading = {"data": {"brand": "CAT", "model": "320D"}, "provenance": {
            "brand": {"source": "plate", "review": "clear", "component": "machine", "asset_id": plate_id},
            "model": {"source": "plate", "review": "clear", "component": "machine", "asset_id": plate_id}},
            "fields": [{"key": "brand", "label": "Marca", "value": "CAT", "source": "plate", "review": "clear",
                        "component": "machine", "asset_id": plate_id, "evidence": "Marca: CAT"},
                       {"key": "model", "label": "Modelo", "value": "320D", "source": "plate", "review": "clear",
                        "component": "machine", "asset_id": plate_id, "evidence": "Modelo: 320D"}],
            "relevance": {"status": "relevant", "accepted_asset_ids": [plate_id]},
            "image_observations": [{"asset_id": plate_id, "kind": "plate", "relevance": "related"}],
            "plates": [], "warnings": [], "questions": []}
        merged = _merge_image_results([repeated, plate_reading], [asset_id, plate_id], ["Excavadoras"])
        self.assertEqual(merged["provenance"]["model"]["source"], "plate")
        self.assertEqual(merged["provenance"]["model"]["review"], "clear")
        self.assertEqual(research_identity(merged, allowed_categories=["Excavadoras"])[1], "model")

        # A newly readable suffix, another image, a plate, a declared value,
        # or changed bytes remains outside the guard.
        self.assertFalse(_preserve_repeated_ambiguous_model(current, self.asset, {}, reading("320DL", "clear")))
        other = self.photo("b")
        other_reading = reading("320D", "clear")
        other_id = str(other.pk)
        for item in (other_reading["provenance"]["model"], other_reading["fields"][0], other_reading["image_observations"][0]):
            item["asset_id"] = other_id
        other_reading["relevance"]["accepted_asset_ids"] = [other_id]
        self.assertFalse(_preserve_repeated_ambiguous_model(current, other, {}, other_reading))
        self.assertFalse(_preserve_repeated_ambiguous_model(current, self.asset,
            {"data": {"model": "Manual"}, "provenance": {"model": {"source": "user", "review": "confirmed"}}},
            reading("320D", "clear")))
        changed_bytes = self.asset.sha256
        self.asset.sha256 = "z" * 64
        self.assertFalse(_preserve_repeated_ambiguous_model(current, self.asset, {}, reading("320D", "clear")))
        self.asset.sha256 = changed_bytes

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
