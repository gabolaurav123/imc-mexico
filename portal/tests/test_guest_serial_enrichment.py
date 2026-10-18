"""One bounded visitor serial supplement; no provider or storage requests."""
from copy import deepcopy
import json
import uuid
from unittest.mock import patch

from django.test import TestCase, override_settings

from portal import guest, services
from portal.models import AnalysisJob, Asset, Category, GuestDraft, PlatformSettings


@override_settings(SECURE_SSL_REDIRECT=False, PRIVATE_S3_BUCKET='', STORAGES={
    'default': {'BACKEND': 'portal.storage.PrivateStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class GuestSerialEnrichmentTests(TestCase):
    def setUp(self):
        self.throttle = patch('portal.guest.throttle', return_value=True)
        self.throttle.start()
        self.addCleanup(self.throttle.stop)
        PlatformSettings.objects.create(pk=1)
        self.category = Category.objects.create(name='Pavimentadoras', slug='pavimentadoras')
        response = self.client.post('/api/invitados/', json.dumps({'category': self.category.pk}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        self.draft = GuestDraft.objects.get(pk=response.json()['id'])
        self.machine = self.draft.machine
        self.asset = Asset.objects.create(machine=self.machine, kind='image', purpose='general',
            processing_status='ready', sha256='a' * 64, original='tests/paver.jpg',
            preview='tests/paver-preview.jpg', mime_type='image/jpeg', size=1)
        self.machine.data.update(brand='Caterpillar', model='TEST-PAVER')
        self.machine.save(update_fields=['data'])
        self.result = {
            'input_snapshot': {'data': deepcopy(self.machine.data)},
            'input_category_id': self.category.pk,
            'data': deepcopy(self.machine.data), 'provenance': {},
            'consistency': {'status': 'insufficient_evidence'},
            'relevance': {'status': 'relevant', 'accepted_asset_ids': [str(self.asset.pk)],
                          'excluded_asset_ids': [], 'uncertain_asset_ids': []},
        }
        self.original = self.job(status='completed', result=deepcopy(self.result),
            application_snapshot=services.automatic_application_snapshot(self.machine))

    def job(self, **changes):
        values = {'machine': self.machine, 'requested_by': self.draft.owner, 'mode': 'analysis',
                  'revision': self.machine.revision, 'auto_apply': True, 'status': 'queued',
                  'asset_ids': [str(self.asset.pk)], 'fingerprint': uuid.uuid4().hex}
        values.update(changes)
        return AnalysisJob.objects.create(**values)

    def add_serial(self, value='PAVER-SERIAL-123'):
        response = self.client.post(f'/api/invitados/{self.draft.pk}/guardar/',
            json.dumps({'revision': self.machine.revision, 'data': {'serial': value}}),
            content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.machine.refresh_from_db()
        return response.json()

    def state(self):
        response = self.client.get(f'/api/invitados/{self.draft.pk}/')
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def analyze(self, **overrides):
        body = {'consent': True, 'revision': self.machine.revision,
                'research': True, 'auto_apply': True, **overrides}
        return self.client.post(f'/api/invitados/{self.draft.pk}/analizar/', json.dumps(body),
                                content_type='application/json')

    def fake_enqueue(self, machine, owner, asset_ids, mode, **kwargs):
        self.assertEqual(machine.pk, self.machine.pk)
        self.assertEqual(owner.pk, self.draft.owner_id)
        self.assertEqual(mode, 'analysis')
        self.assertTrue(kwargs['auto_apply'])
        self.assertTrue(kwargs['authorize_ai'])
        self.assertTrue(kwargs['research'])
        return self.job(asset_ids=asset_ids or [str(self.asset.pk)])

    def test_save_contract_exposes_new_serial_allowance_and_one_job_consumes_it(self):
        self.assertFalse(self.state()['serial_enrichment_available'])
        saved = self.add_serial()
        self.assertTrue(saved['machine']['serial_enrichment_available'])
        self.assertTrue(self.state()['analysis_used'])
        with patch('portal.processing.enqueue_analysis', side_effect=self.fake_enqueue) as enqueue:
            response = self.analyze(asset_ids=[str(self.asset.pk)])
            self.assertEqual(response.status_code, 200, response.content)
            self.assertFalse(response.json()['guest_draft']['serial_enrichment_available'])
            # A repeated/concurrent browser event sees the queued reservation.
            duplicate = self.analyze(asset_ids=[str(self.asset.pk)])
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(enqueue.call_count, 1)
        self.assertEqual(self.machine.analysis_jobs.count(), 2)

    def test_all_current_photos_cannot_be_omitted_or_replaced_by_client_selection(self):
        self.add_serial()
        with patch('portal.processing.enqueue_analysis') as enqueue:
            for selection in ([], [str(uuid.uuid4())], [str(self.asset.pk), str(uuid.uuid4())]):
                with self.subTest(selection=selection):
                    response = self.analyze(asset_ids=selection)
                    self.assertEqual(response.status_code, 400)
        enqueue.assert_not_called()
        self.assertTrue(self.state()['serial_enrichment_available'])
        with patch('portal.processing.enqueue_analysis', side_effect=self.fake_enqueue):
            self.assertEqual(self.analyze().status_code, 200)  # Omission selects all checked photos.

    def test_new_serial_cannot_reopen_a_running_completed_or_nonservice_failed_supplement(self):
        self.add_serial()
        for status in ('queued', 'running', 'completed', 'failed'):
            with self.subTest(status=status):
                second = self.job(status=status)
                self.machine.data['serial'] = 'A-DIFFERENT-SERIAL-456'
                self.machine.save(update_fields=['data'])
                self.assertFalse(guest._serial_enrichment_available(self.machine))
                with patch('portal.processing.enqueue_analysis') as enqueue:
                    self.assertEqual(self.analyze().status_code, 400)
                enqueue.assert_not_called()
                second.delete()

    def test_service_failures_allow_only_the_existing_bounded_retries(self):
        self.add_serial()
        with patch('portal.processing.enqueue_analysis', side_effect=self.fake_enqueue) as enqueue:
            for failure_code in ('billing_unavailable', 'credentials_unavailable', 'model_unavailable'):
                self.assertTrue(self.state()['serial_enrichment_available'])
                response = self.analyze()
                self.assertEqual(response.status_code, 200, response.content)
                job = AnalysisJob.objects.get(pk=response.json()['id'])
                job.status = 'failed'
                job.result = {'provider_error_code': failure_code}
                job.save(update_fields=['status', 'result'])
            self.assertFalse(self.state()['serial_enrichment_available'])
            response = self.analyze()
        self.assertEqual(response.status_code, 400)
        self.assertIn('varios intentos', response.json()['error'])
        self.assertEqual(enqueue.call_count, guest.MAX_GUEST_SERVICE_RETRIES)

    def test_original_serial_or_equivalent_ocr_reading_does_not_buy_another_run(self):
        self.add_serial('PAVER-SERIAL-123')
        for result in (
            {**self.result, 'input_snapshot': {'data': {'serial': 'ANY-INITIAL-SERIAL'}}},
            {**self.result, 'data': {'serial': ' paver serial 123 '}},
        ):
            with self.subTest(result=result):
                self.original.result = result
                self.original.save(update_fields=['result'])
                self.assertFalse(self.state()['serial_enrichment_available'])

    def test_placeholder_serial_never_qualifies(self):
        for serial in ('', 'no tengo', 'sin número de serie', '---', 'ab'):
            with self.subTest(serial=serial):
                self.add_serial(serial)
                self.assertFalse(self.state()['serial_enrichment_available'])

    def test_changed_photo_hash_purpose_kind_or_status_invalidates_the_allowance(self):
        self.add_serial()
        for field, changed in (('sha256', 'b' * 64), ('purpose', 'detail'), ('kind', 'video'),
                               ('processing_status', 'pending')):
            with self.subTest(field=field):
                previous = getattr(self.asset, field)
                setattr(self.asset, field, changed)
                self.asset.save(update_fields=[field])
                self.assertFalse(self.state()['serial_enrichment_available'])
                setattr(self.asset, field, previous)
                self.asset.save(update_fields=[field])

    def test_added_photo_or_changed_category_invalidates_the_allowance(self):
        self.add_serial()
        extra = Asset.objects.create(machine=self.machine, kind='image', purpose='general',
            processing_status='ready', sha256='b' * 64, original='tests/other.jpg', size=1)
        self.assertFalse(self.state()['serial_enrichment_available'])
        extra.delete()
        other = Category.objects.create(name='Excavadoras', slug='excavadoras')
        self.machine.category = other
        self.machine.save(update_fields=['category'])
        self.assertFalse(self.state()['serial_enrichment_available'])

    def test_unaccepted_uncertain_conflicting_or_preflight_photos_never_qualify(self):
        self.add_serial()
        cases = (
            {'preflight': True}, {'blocking_reason': 'category_conflict'},
            {'consistency': {'status': 'contradiction'}},
            {'relevance': {'status': 'unrelated', 'accepted_asset_ids': [str(self.asset.pk)]}},
            {'relevance': {'status': 'uncertain', 'accepted_asset_ids': [str(self.asset.pk)]}},
            {'relevance': {'status': 'relevant', 'accepted_asset_ids': []}},
            {'relevance': {**self.result['relevance'], 'excluded_asset_ids': [str(self.asset.pk)]}},
            {'relevance': {**self.result['relevance'], 'uncertain_asset_ids': [str(self.asset.pk)]}},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                self.original.result = {**self.result, **changes}
                self.original.save(update_fields=['result'])
                self.assertFalse(self.state()['serial_enrichment_available'])

    def test_incomplete_historical_contract_fails_closed_without_a_500(self):
        self.add_serial()
        cases = (
            {'input_snapshot': None}, {'input_snapshot': {}}, {'input_snapshot': {'data': []}},
            {'data': []}, {'consistency': []}, {'relevance': []},
            {'relevance': {**self.result['relevance'], 'accepted_asset_ids': None}},
            {'relevance': {**self.result['relevance'], 'accepted_asset_ids': {str(self.asset.pk): True}}},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                self.original.result = {**self.result, **changes}
                self.original.save(update_fields=['result'])
                self.assertFalse(self.state()['serial_enrichment_available'])
        self.original.result = self.result
        self.original.asset_ids = {str(self.asset.pk): True}
        self.original.save(update_fields=['result', 'asset_ids'])
        self.assertFalse(self.state()['serial_enrichment_available'])
        self.original.asset_ids = None
        self.assertFalse(guest._serial_enrichment_available(self.machine, [self.original]))
