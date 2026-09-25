"""The worker reaches local family references after inconclusive exact research."""
from io import BytesIO
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from portal.family_reference import build_family_reference, is_validated_family_reference
from portal.models import Machine, MachineVersion, PlatformSettings, Publication, User
from portal.processing import MachineAnalysis, enqueue_analysis, ingest_asset, process_next_job
from portal.research import UsageTotals, empty_research
from portal.tests import test_family_reference as family_fixtures


@override_settings(OPENAI_API_KEY='synthetic-no-provider-request', OPENAI_MODEL='gpt-6-luna', PRIVATE_S3_BUCKET='')
class FamilyPipelineTests(TestCase):
    technical = family_fixtures.FamilyReferenceTests.technical
    market = family_fixtures.FamilyReferenceTests.market

    def setUp(self):
        family_fixtures.FamilyReferenceTests.setUp(self)
        folder = TemporaryDirectory(prefix='imc-family-pipeline-')
        self.addCleanup(folder.cleanup)
        override = override_settings(MEDIA_ROOT=folder.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(email='family-pipeline@example.invalid', is_test=True)
        self.machine = Machine.objects.create(owner=self.user, category=self.category)
        PlatformSettings.objects.create(ai_enabled=True, ai_daily_token_limit=300000)
        output = BytesIO()
        Image.new('RGB', (80, 80), 'yellow').save(output, format='JPEG')
        self.asset = ingest_asset(self.machine, self.user, SimpleUploadedFile('synthetic.jpg', output.getvalue()))
        self.technical(self.base, 2007, 2020)
        self.technical(self.long, 2006, 2014)
        self.market(self.base, 'one', '60000')
        self.market(self.long, 'two', '75900')

    def test_worker_adds_signed_family_ranges_and_applies_them_without_extra_provider_calls(self):
        parsed = MachineAnalysis(title='Excavadora CAT', description='', category='Excavadoras',
            fields=[dict(key='brand', label='Marca', value='CAT', source='image', review='clear',
                         component='machine', asset_id='image_001', evidence='Marca CAT legible'),
                    dict(key='model', label='Modelo', value=None, source='image', review='needs_review',
                         component='machine', asset_id='image_001',
                         evidence='El rótulo muestra «320D» y un sufijo no confirmable.')],
            plates=[], warnings=[], questions=[], image_observations=[dict(asset_id='image_001',
                kind='machine', relevance='machinery', category='Excavadoras',
                visual_assessment={'usage_condition':'Usada'})])
        job = enqueue_analysis(self.machine, self.user, asset_ids=[str(self.asset.pk)],
                               research=True, authorize_ai=True, auto_apply=True,
                               expected_revision=self.machine.revision)
        with patch('openai.OpenAI') as provider, \
                patch('portal.processing.research_machine', return_value=(empty_research('no_results'), UsageTotals())) as research, \
                patch('portal.processing.estimate_machine', return_value=({'status':'insufficient','fields':{}}, UsageTotals())) as valuation, \
                patch('portal.processing.build_family_reference', wraps=build_family_reference) as family_lookup:
            client = provider.return_value
            client.responses.parse.return_value = SimpleNamespace(status='completed', output_parsed=parsed,
                model='gpt-6-luna', usage=SimpleNamespace(input_tokens=200, output_tokens=90))
            self.assertTrue(process_next_job())

        research.assert_called_once()
        valuation.assert_called_once()
        family_lookup.assert_called_once()
        self.assertEqual(family_lookup.call_args.kwargs['category'].pk, self.category.pk)
        client.responses.parse.assert_called_once()
        client.responses.create.assert_not_called()
        client.close.assert_called_once()
        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual((job.status, job.attempts), ('completed', 1))
        self.assertEqual((job.input_tokens, job.output_tokens), (200, 90))
        self.assertTrue(is_validated_family_reference(job.result['family_reference']))
        self.assertEqual(job.result['family_reference']['identity']['scope'], 'family')
        self.assertEqual(job.result['family_reference']['identity']['asset_id'], str(self.asset.pk))
        self.assertEqual(self.machine.data['model_family'], '320D')
        self.assertEqual((self.machine.data['estimated_year_from'], self.machine.data['estimated_year_to']), (2006, 2020))
        self.assertEqual((self.machine.data['estimate_min'], self.machine.data['estimate_max'], self.machine.data['estimate_currency']), (60000, 75900, 'USD'))
        self.assertEqual(self.machine.provenance['model_family']['source'], 'family_reference')
        self.assertEqual(self.machine.provenance['model_family']['identity_scope'], 'family')
        self.assertEqual(job.application_result['status'], 'applied')
        self.assertTrue({'model_family','estimated_year_from','estimated_year_to','estimate_min','estimate_max'} <= set(job.application_result['applied_fields']))
        for exact in ('model','year','price','condition','weight','power','estimate_suggested_price'):
            self.assertFalse(self.machine.data.get(exact), exact)
        self.assertIn('familia 320D', self.machine.data['description'])
        self.assertIn('Año aproximado: 2006–2020.', self.machine.data['description'])
        self.assertEqual(self.machine.status, 'draft')
        self.assertFalse(MachineVersion.objects.exists())
        self.assertFalse(Publication.objects.exists())
