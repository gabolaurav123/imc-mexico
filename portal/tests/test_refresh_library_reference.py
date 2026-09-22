from io import StringIO
from django.core.management import call_command
from django.test import TestCase

from portal.models import Brand, Category, EquipmentModel, Machine, User, AnalysisJob, Consent, Asset
from portal.services import machine_valuation


class RefreshLibraryReferenceTests(TestCase):
    def prepare_reference_case(self):
        call_command('seed', stdout=StringIO())
        self.machine.data = {'brand': 'Caterpillar', 'model': '320D L', 'usage_condition': 'Usada',
                             'price': 99999, 'currency': 'MXN'}
        self.machine.provenance = {
            'brand': {'source': 'image', 'review': 'clear', 'component': 'machine'},
            'model': {'source': 'image', 'review': 'clear', 'component': 'machine'},
            'usage_condition': {'source': 'visual_proposal', 'review': 'needs_review'},
            'price': {'source': 'user', 'review': 'confirmed'},
            'currency': {'source': 'user', 'review': 'confirmed'}}
        self.machine.save()
        asset = Asset.objects.create(machine=self.machine, original='test/photo.jpg',
            kind='image', purpose='general', processing_status='ready', size=1, mime_type='image/jpeg', sha256='a'*64)
        AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, revision=self.machine.revision,
            status='completed', fingerprint='prior', asset_ids=[str(asset.pk)], result={'relevance': {'status': 'relevant'}})
        Consent.objects.create(user=self.user, machine=self.machine, kind='ai', granted=True)

    def test_actual_release_references_fill_age_and_price_preserving_owner_price(self):
        self.prepare_reference_case()
        output = StringIO()
        call_command('refresh_library_reference', str(self.machine.pk), '--apply', stdout=output)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.data.get('estimated_year_from'), 2006, output.getvalue())
        self.assertEqual(self.machine.data.get('estimated_year_to'), 2014)
        self.assertEqual(float(self.machine.data['estimate_min']), 66900)
        self.assertEqual(float(self.machine.data['estimate_max']), 75900)
        self.assertEqual(self.machine.data['estimate_currency'], 'USD')
        self.assertEqual((self.machine.data['price'], self.machine.data['currency']), (99999, 'MXN'))
        self.assertEqual(float(machine_valuation(self.machine)['suggested_price']), 71400)
        job = self.machine.analysis_jobs.first()
        self.assertEqual(job.model, 'reviewed-library')
        self.assertEqual((job.input_tokens, job.output_tokens), (0, 0))

    def test_new_assets_and_revocation_prevent_reference_application(self):
        self.prepare_reference_case()
        Consent.objects.create(user=self.user, machine=self.machine, kind='ai', granted=False)
        call_command('refresh_library_reference', str(self.machine.pk), '--apply', stdout=StringIO())
        self.assertEqual(self.machine.analysis_jobs.count(), 1)
        Consent.objects.create(user=self.user, machine=self.machine, kind='ai', granted=True)
        Asset.objects.create(machine=self.machine, original='test/other.jpg', kind='image',
            processing_status='ready', size=1, mime_type='image/jpeg', sha256='b'*64)
        call_command('refresh_library_reference', str(self.machine.pk), '--apply', stdout=StringIO())
        self.assertEqual(self.machine.analysis_jobs.count(), 1)
    def setUp(self):
        self.user=User.objects.create_user(email='refresh@example.invalid', is_test=True)
        self.category=Category.objects.create(name='Excavadoras',slug='excavadoras')
        brand=Brand.objects.create(name='Caterpillar')
        EquipmentModel.objects.create(brand=brand,name='320D L',category=self.category)
        self.machine=Machine.objects.create(owner=self.user,category=self.category,
            data={'brand':'Caterpillar','model':'320D L','year':2007,'price':99999},
            provenance={'brand':{'source':'user','review':'confirmed'},'model':{'source':'image','review':'clear'},
                        'year':{'source':'user','review':'confirmed'},'price':{'source':'user','review':'confirmed'}})

    def test_dry_run_never_creates_a_job_or_changes_human_price_and_year(self):
        output=StringIO(); before=self.machine.revision
        call_command('refresh_library_reference',str(self.machine.pk),stdout=output)
        self.machine.refresh_from_db()
        self.assertFalse(AnalysisJob.objects.filter(machine=self.machine).exists())
        self.assertEqual((self.machine.revision,self.machine.data['price'],self.machine.data['year']),(before,99999,2007))
        self.assertIn(self.machine.folio,output.getvalue())

    def test_apply_without_current_ai_consent_records_no_machine_update(self):
        # A revoked consent does not create a new candidate or change the draft.
        output=StringIO(); before=self.machine.revision
        call_command('refresh_library_reference',str(self.machine.pk),'--apply',stdout=output)
        self.machine.refresh_from_db()
        self.assertFalse(AnalysisJob.objects.filter(machine=self.machine).exists())
        self.assertEqual((self.machine.revision,self.machine.data['price'],self.machine.data['year']),(before,99999,2007))
