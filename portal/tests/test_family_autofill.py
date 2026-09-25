"""A signed family reference fills only editable ranges, never exact identity."""
from copy import deepcopy
import json
import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase

from portal.commercial import AGE_LABELS, ESTIMATE_LABELS
from portal.family_reference import build_family_reference, merge_family_reference
from portal.models import AnalysisJob, Asset, Consent, Machine, MachineVersion, Publication, User
from portal.public_data import public_json
from portal.research import research_identity
from portal.services import (apply_analysis_automatically, apply_analysis_suggestions,
                             automatic_application_snapshot, save_draft)
from portal.tests import test_family_reference as family_fixtures


class FamilyAutofillTests(TestCase):
    technical = family_fixtures.FamilyReferenceTests.technical
    market = family_fixtures.FamilyReferenceTests.market

    def setUp(self):
        family_fixtures.FamilyReferenceTests.setUp(self)
        self.user = User.objects.create_user(email='family-autofill@example.invalid', is_test=True)
        self.machine = Machine.objects.create(owner=self.user, category=self.category)
        self.asset = Asset.objects.create(machine=self.machine, kind='image', processing_status='ready',
            purpose='general', original='synthetic/family.jpg', size=1, mime_type='image/jpeg', sha256='f' * 64)
        Consent.objects.create(user=self.user, machine=self.machine, kind='ai', granted=True)
        self.technical(self.base, 2007, 2020)
        self.technical(self.long, 2006, 2014)
        self.market(self.base, 'one', '60000')
        self.market(self.long, 'two', '75900')

    def result(self):
        raw = json.loads(json.dumps(family_fixtures.FamilyReferenceTests.result(self)).replace('image-1', str(self.asset.pk)))
        raw['relevance']['status'] = 'machinery'
        family = build_family_reference(raw, category=self.category)
        self.assertIsNotNone(family)
        return merge_family_reference(raw, family)

    def job(self, result=None):
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, status='completed',
            revision=self.machine.revision, auto_apply=True, application_snapshot=automatic_application_snapshot(self.machine),
            asset_ids=[str(self.asset.pk)], fingerprint=uuid.uuid4().hex, result=deepcopy(result or self.result()))

    def apply(self, job=None):
        self.machine, outcome = apply_analysis_automatically(self.machine, self.user, job or self.job(), self.machine.revision)
        return outcome

    def edit(self, **data):
        self.machine = save_draft(self.machine, self.user, {'data': data}, self.machine.revision)

    def test_signed_family_populates_ranges_but_never_exact_model_year_price_or_specs(self):
        outcome = self.apply()
        self.assertEqual(self.machine.data['model_family'], '320D')
        self.assertFalse(self.machine.data.get('model'))
        self.assertEqual((self.machine.data['estimated_year_from'], self.machine.data['estimated_year_to']), (2006, 2020))
        self.assertEqual((self.machine.data['estimate_min'], self.machine.data['estimate_max'], self.machine.data['estimate_currency']), (60000, 75900, 'USD'))
        self.assertFalse({'year', 'price', 'weight', 'power', 'estimate_suggested_price'} & self.machine.data.keys())
        self.assertTrue({'model_family', *AGE_LABELS, 'estimate_min', 'estimate_max', 'estimate_currency'} <= set(outcome['applied_fields']))
        for key in ('model_family', *AGE_LABELS, 'estimate_min', 'estimate_max', 'estimate_currency'):
            self.assertEqual(self.machine.provenance[key]['source'], 'family_reference')
            self.assertEqual(self.machine.provenance[key]['review'], 'needs_review')
            self.assertEqual(self.machine.provenance[key]['identity_scope'], 'family')
        exact, basis = research_identity({'data': self.machine.data, 'provenance': self.machine.provenance},
                                        {'data': self.machine.data, 'provenance': self.machine.provenance})
        self.assertIsNone(exact['model'])
        self.assertNotEqual(basis, 'model')
        self.assertFalse(MachineVersion.objects.exists())
        self.assertFalse(Publication.objects.exists())

    def test_family_edit_during_analysis_blocks_all_family_values(self):
        job = self.job()
        self.edit(model_family='320D2')
        self.apply(job)
        self.assertEqual(self.machine.data['model_family'], '320D2')
        self.assertFalse(AGE_LABELS.keys() & self.machine.data.keys())
        self.assertFalse(ESTIMATE_LABELS.keys() & self.machine.data.keys())

    def test_deliberate_family_clear_during_analysis_is_preserved(self):
        job = self.job()
        self.edit(model_family='')
        self.apply(job)
        self.assertEqual(self.machine.data['model_family'], '')
        self.assertFalse(AGE_LABELS.keys() & self.machine.data.keys())
        self.assertFalse(ESTIMATE_LABELS.keys() & self.machine.data.keys())

    def test_human_range_and_exact_year_price_win_over_family_suggestions(self):
        job = self.job()
        self.edit(estimate_min=70000, estimate_max=80000, estimate_currency='MXN', year=2011, price=72500, currency='MXN')
        self.apply(job)
        self.assertEqual((self.machine.data['estimate_min'], self.machine.data['estimate_max'], self.machine.data['estimate_currency']), (70000, 80000, 'MXN'))
        self.assertEqual((self.machine.data['year'], self.machine.data['price'], self.machine.data['currency']), (2011, 72500, 'MXN'))
        self.assertFalse(AGE_LABELS.keys() & self.machine.data.keys())

    def test_brand_correction_retires_automatic_family_values_only(self):
        self.apply()
        self.edit(description='Descripción corregida por el propietario.')
        self.edit(brand='Komatsu')
        self.assertNotIn('model_family', self.machine.data)
        self.assertFalse(AGE_LABELS.keys() & self.machine.data.keys())
        self.assertFalse(ESTIMATE_LABELS.keys() & self.machine.data.keys())
        self.assertEqual(self.machine.data['description'], 'Descripción corregida por el propietario.')

    def test_exact_model_incompatible_with_family_blocks_application(self):
        job = self.job()
        self.edit(model='320D2')
        self.apply(job)
        self.assertEqual(self.machine.data['model'], '320D2')
        self.assertNotIn('model_family', self.machine.data)
        self.assertNotIn('estimate_min', self.machine.data)
        self.assertNotIn('estimated_year_from', self.machine.data)

    def test_forged_amount_does_not_apply_a_partial_range(self):
        result = self.result()
        result['data']['estimate_min'] = '1.00'
        self.apply(self.job(result))
        self.assertFalse({'estimate_min', 'estimate_max', 'estimate_currency'} & self.machine.data.keys())
        self.assertEqual(self.machine.data['model_family'], '320D')
        self.assertIn('estimated_year_from', self.machine.data)

    def test_tampered_manifest_and_raw_visual_family_are_not_automatically_applied(self):
        result = self.result()
        result['family_reference']['fields']['estimated_year_from'] = 1900
        self.apply(self.job(result))
        self.assertNotIn('model_family', self.machine.data)
        self.assertFalse(AGE_LABELS.keys() & self.machine.data.keys())
        raw = self.result()
        raw['provenance']['model_family']['source'] = 'image'
        raw['provenance']['model_family']['review'] = 'clear'
        self.apply(self.job(raw))
        self.assertNotIn('model_family', self.machine.data)

    def test_human_confirmed_family_is_not_lost_when_other_identity_changes(self):
        self.apply()
        self.machine = save_draft(self.machine, self.user, {
            'data': {'model_family': '320D'}, 'provenance': {'model_family': {'source': 'user', 'review': 'confirmed'}}},
            self.machine.revision)
        self.edit(brand='Komatsu')
        self.assertEqual(self.machine.data['model_family'], '320D')
        self.assertEqual(self.machine.provenance['model_family']['review'], 'confirmed')
        self.assertNotIn('estimate_min', self.machine.data)

    def test_explicit_acceptance_rejects_unsigned_family_values(self):
        result = self.result()
        result['data']['model_family'] = '320D2'
        job = self.job(result)
        with self.assertRaises(ValidationError):
            apply_analysis_suggestions(self.machine, self.user, job, ['model_family'], self.machine.revision)

    def test_public_projection_exposes_family_without_exact_model_or_private_evidence(self):
        self.apply()
        self.edit(serial='PRIVATE-SN-1234')
        exported = public_json({'data': {**self.machine.data, 'family_reference': self.result()['family_reference']},
                                'provenance': self.machine.provenance})
        self.assertEqual(exported['data']['model_family'], '320D')
        self.assertFalse(exported['data'].get('model'))
        text = json.dumps(exported)
        for forbidden in ('family_reference', 'identity_scope', 'provenance', 'PRIVATE-SN-1234', 'marketone.example.com'):
            self.assertNotIn(forbidden, text)
        self.edit(model_family='PRIVATE-SN-1234')
        self.assertNotIn('model_family', public_json({'data': self.machine.data})['data'])

    def test_browser_cannot_forge_family_provenance(self):
        self.machine = save_draft(self.machine, self.user, {
            'data': {'model_family': '320D'},
            'provenance': {'model_family': {'source': 'family_reference', 'review': 'needs_review', 'identity_scope': 'family'}}},
            self.machine.revision)
        self.assertEqual(self.machine.provenance['model_family']['source'], 'user')
        self.assertEqual(self.machine.provenance['model_family']['review'], 'confirmed')
        self.assertNotIn('identity_scope', self.machine.provenance['model_family'])
