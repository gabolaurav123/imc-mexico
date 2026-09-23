"""Regression coverage for a recovered model suffix after image reading."""
from copy import deepcopy
from io import BytesIO, StringIO
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image
from pypdf import PdfReader

from portal.knowledge import research_from_knowledge
from portal.market_catalogue import valuation_from_library
from portal.models import AnalysisJob, Asset, Category, Consent, Machine, User
from portal.pdf import build_pdf
from portal.research import merge_research
from portal.services import (apply_analysis_automatically, automatic_application_snapshot,
    save_draft)


@override_settings(PRIVATE_S3_BUCKET='', SECURE_SSL_REDIRECT=False)
class EstimateRecoveryTests(TestCase):
    """A missed suffix must be correctable by a later clear reading of the same photo."""

    def setUp(self):
        self.media_root = self.enterContext(TemporaryDirectory(prefix='imc-estimate-recovery-'))
        self.enterContext(override_settings(MEDIA_ROOT=self.media_root))
        call_command('seed', stdout=StringIO())
        self.owner = User.objects.create_user(email='estimate-recovery@example.invalid', is_test=True)
        self.category = Category.objects.get(slug='excavadoras')
        self.machine = Machine.objects.create(owner=self.owner, category=self.category,
            data={'brand': 'Caterpillar', 'model': '320D', 'condition': 'Usada',
                  'price': 99999, 'currency': 'MXN'},
            provenance={
                'brand': {'source': 'image', 'review': 'clear', 'component': 'machine'},
                'model': {'source': 'image', 'review': 'clear', 'component': 'machine'},
                'condition': {'source': 'user', 'review': 'confirmed'},
                'price': {'source': 'user', 'review': 'confirmed'},
                'currency': {'source': 'user', 'review': 'confirmed'},
            })
        raw = BytesIO()
        Image.new('RGB', (80, 60), 'gold').save(raw, format='JPEG')
        self.asset = Asset(machine=self.machine, kind='image', purpose='general', processing_status='ready',
            mime_type='image/jpeg', sha256='3' * 64, size=len(raw.getvalue()))
        self.asset.original.save('320d.jpg', ContentFile(raw.getvalue()), save=False)
        self.asset.preview.save('320d-preview.jpg', ContentFile(raw.getvalue()), save=False)
        self.asset.save()
        Consent.objects.create(user=self.owner, machine=self.machine, kind='ai', granted=True)

        # Reproduce the prior automatic reading that omitted the small suffix.
        prior = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, asset_ids=[str(self.asset.pk)], fingerprint=uuid4().hex,
            status='completed', result={'relevance': {'status': 'relevant'}})
        self.machine.provenance['brand']['analysis_id'] = str(prior.pk)
        self.machine.provenance['model']['analysis_id'] = str(prior.pk)
        self.machine.save(update_fields=['provenance'])

    def _result_for_corrected_reading(self):
        source = {'source': 'image', 'review': 'clear', 'component': 'machine',
                  'asset_id': str(self.asset.pk), 'evidence': 'Rótulo visible: Caterpillar 320D L.'}
        result = {'data': {'brand': 'Caterpillar', 'model': '320D L'},
                  'provenance': {'brand': deepcopy(source), 'model': deepcopy(source)},
                  'fields': [], 'warnings': [], 'plates': [],
                  'relevance': {'status': 'relevant'}}
        identity = {'brand': 'Caterpillar', 'model': '320D L', 'serial': None}
        research = research_from_knowledge(result, {'data': self.machine.data,
            'provenance': self.machine.provenance}, self.category, identity)
        self.assertIsNotNone(research)
        merge_research(result, research, {'data': self.machine.data, 'provenance': self.machine.provenance})
        valuation = valuation_from_library({'brand': 'Caterpillar', 'model': '320D L',
            'condition': 'used', 'configurations': {}, 'compatibility': {}, 'market_hint': None}, self.category)
        self.assertIsNotNone(valuation)
        self.assertEqual(valuation['status'], 'estimated')
        result['valuation'] = valuation
        for key, value in valuation['fields'].items():
            if value not in (None, ''):
                result['data'][key] = value
                result['provenance'][key] = {'source': 'valuation', 'review': 'needs_review',
                                             'component': 'machine'}
        return result

    def _job(self, result):
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, asset_ids=[str(self.asset.pk)], fingerprint=uuid4().hex,
            status='completed', auto_apply=True, application_snapshot=automatic_application_snapshot(self.machine),
            result=result)

    def test_recovered_suffix_updates_library_period_and_value_without_overwriting_owner_price(self):
        job = self._job(self._result_for_corrected_reading())
        self.machine, summary = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        self.machine.refresh_from_db()
        self.assertEqual(summary['status'], 'applied')
        self.assertEqual(self.machine.data['model'], '320D L')
        self.assertEqual((self.machine.data['estimated_year_from'], self.machine.data['estimated_year_to']), (2006, 2014))
        self.assertEqual((float(self.machine.data['estimate_min']), float(self.machine.data['estimate_max']),
                          self.machine.data['estimate_currency']), (66900, 75900, 'USD'))
        self.assertEqual((self.machine.data['price'], self.machine.data['currency']), (99999, 'MXN'))

        version = SimpleNamespace(pk=uuid4(), number=1, created_at=self.machine.updated_at,
            data={'title': self.machine.title, 'data': self.machine.data, 'provenance': self.machine.provenance,
                  'category_name': self.category.name, 'asset_ids': [str(self.asset.pk)],
                  'public_asset_ids': [str(self.asset.pk)], 'contact_authorized': False})
        pdf = PdfReader(BytesIO(build_pdf(self.machine, self.machine.data, [self.asset], public=False, version=version)))
        first_page = pdf.pages[0].extract_text() or ''
        for text in ('320D L', '2006–2014', '66,900–75,900 USD'):
            self.assertIn(text, ' '.join(first_page.split()))

    def test_human_reversion_to_320d_blocks_l_references_and_value(self):
        job = self._job(self._result_for_corrected_reading())
        self.machine = save_draft(self.machine, self.owner,
            {'data': {'model': '320D'}, 'provenance': {'model': {'source': 'user', 'review': 'confirmed'}}},
            self.machine.revision)
        self.machine, summary = apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.data['model'], '320D')
        self.assertEqual(summary['field_reasons']['model'], 'existing_value')
        for key in ('estimated_year_from', 'estimated_year_to', 'estimate_min', 'estimate_max', 'estimate_currency'):
            self.assertNotIn(key, self.machine.data)
        for key in ('estimated_year_from', 'estimated_year_to'):
            self.assertEqual(summary['field_reasons'][key], 'identity_changed')
