"""Approximate year ranges are one editable proposal, never an exact year."""
from copy import deepcopy

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from portal.commercial import AGE_LABELS
from portal.services import save_draft, apply_analysis_suggestions, public_web_references, web_research_for_provenance
from portal.tests import test_commercial_autofill as fixtures
from portal.tests.test_image_relevance import field, observation, parsed
from portal.tests.test_visual_assessment import normalize


class AgeAutofillTests(TestCase):
    job = fixtures.CommercialAutofillTests.job
    apply = fixtures.CommercialAutofillTests.apply

    def setUp(self):
        fixtures.CommercialAutofillTests.setUp(self)

    def result(self, start=1990, end=2005):
        asset = str(self.asset.pk)
        return normalize(parsed([observation(asset, age_estimate={
            'start_year': start, 'end_year': end,
            'basis': 'Cabina angular, mandos mecánicos y diseño del bastidor de una generación anterior.'})],
            [field('brand', 'Caterpillar', asset), field('model', '2EC25', asset)]), [asset])

    def edit(self, **data):
        self.machine = save_draft(self.machine, self.user, {'data': data}, self.machine.revision)

    def test_range_and_basis_fill_together_without_becoming_exact_year(self):
        outcome = self.apply(self.job(self.result()))
        self.assertTrue(AGE_LABELS.keys() <= set(outcome['applied_fields']))
        self.assertEqual(self.machine.data['estimated_year_from'], 1990)
        self.assertEqual(self.machine.data['estimated_year_to'], 2005)
        self.assertNotIn('year', self.machine.data)
        self.assertIn('Año aproximado', self.machine.data['description'])
        for key in AGE_LABELS:
            self.assertEqual(self.machine.provenance[key]['review'], 'needs_review')

    def test_partial_or_forged_automatic_range_is_not_applied(self):
        base = self.result()
        variants = []
        missing = deepcopy(base)
        missing['data'].pop('estimated_year_to')
        variants.append(missing)
        forged = deepcopy(base)
        forged['data']['estimated_year_from'] = 1900
        variants.append(forged)
        wrong_source = deepcopy(base)
        wrong_source['provenance']['estimated_year_to']['source'] = 'image'
        wrong_source['provenance']['estimated_year_to']['review'] = 'clear'
        variants.append(wrong_source)
        for result in variants:
            with self.subTest(result=result['data']):
                self.apply(self.job(result))
                self.assertFalse(AGE_LABELS.keys() & self.machine.data.keys())

    def test_human_single_bound_and_deliberate_clear_protect_entire_range(self):
        self.apply(self.job(self.result()))
        self.edit(estimated_year_from=1995)
        before = deepcopy(self.machine.data)
        self.apply(self.job(self.result(2000, 2010)))
        self.assertEqual({k: self.machine.data[k] for k in AGE_LABELS}, {k: before[k] for k in AGE_LABELS})
        self.edit(estimated_year_from=None, estimated_year_to=None, estimated_year_basis='')
        self.apply(self.job(self.result()))
        self.assertIsNone(self.machine.data['estimated_year_from'])
        self.assertIsNone(self.machine.data['estimated_year_to'])
        self.assertEqual(self.machine.data['estimated_year_basis'], '')
        self.assertNotIn('Año aproximado:', self.machine.data['description'])

    def test_inflight_edit_cannot_be_overwritten_by_completed_range(self):
        job = self.job(self.result())
        self.edit(estimated_year_from=1980, estimated_year_to=1995, estimated_year_basis='Revisado por el dueño')
        self.apply(job)
        self.assertEqual(self.machine.data['estimated_year_from'], 1980)
        self.assertEqual(self.machine.data['estimated_year_to'], 1995)
        self.assertEqual(self.machine.data['estimated_year_basis'], 'Revisado por el dueño')

    def test_exact_year_prevents_automatic_range_and_retires_previous_one(self):
        self.apply(self.job(self.result()))
        self.edit(year=2001)
        self.assertFalse(AGE_LABELS.keys() & self.machine.data.keys())
        self.assertNotIn('Año aproximado:', self.machine.data['description'])
        self.apply(self.job(self.result()))
        self.assertEqual(self.machine.data['year'], 2001)
        self.assertFalse(AGE_LABELS.keys() & self.machine.data.keys())

    def test_identity_edit_retires_automatic_range_but_preserves_manual_description(self):
        self.apply(self.job(self.result()))
        self.edit(description='Texto del propietario')
        self.edit(model='OTHER MODEL')
        self.assertFalse(AGE_LABELS.keys() & self.machine.data.keys())
        self.assertEqual(self.machine.data['description'], 'Texto del propietario')

    def test_numeric_bounds_are_current_integral_and_ordered_but_editable_partial(self):
        for values in ({'estimated_year_from': 1899}, {'estimated_year_to': timezone.now().year + 1},
                       {'estimated_year_from': True}, {'estimated_year_from': 'NaN'},
                       {'estimated_year_from': 1990.5}, {'estimated_year_from': 2010, 'estimated_year_to': 2000}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self.edit(**values)
        self.edit(estimated_year_from=1990)
        self.assertEqual(self.machine.data['estimated_year_from'], 1990)
        self.edit(estimated_year_to=2000)
        self.assertEqual(self.machine.data['estimated_year_to'], 2000)

    def test_explicit_apply_requires_whole_validated_range(self):
        job = self.job(self.result())
        with self.assertRaises(ValidationError):
            apply_analysis_suggestions(self.machine, self.user, job, ['estimated_year_from'], self.machine.revision)
        self.machine = apply_analysis_suggestions(self.machine, self.user, job, list(AGE_LABELS), self.machine.revision)
        self.assertEqual(self.machine.data['estimated_year_to'], 2005)
        self.assertNotIn('year', self.machine.data)

    def test_owner_range_survives_exact_year_and_reanalysis(self):
        self.edit(estimated_year_from=1990, estimated_year_to=2000, estimated_year_basis='Rango declarado')
        self.edit(year=1998)
        self.apply(self.job(self.result()))
        self.assertEqual(self.machine.data['estimated_year_from'], 1990)
        self.assertEqual(self.machine.data['estimated_year_to'], 2000)
        self.assertEqual(self.machine.data['year'], 1998)

    def test_documented_model_period_applies_atomically_with_its_references(self):
        from portal.research import merge_research
        from portal.tests.test_model_year_period import research
        self.edit(model='14H')
        result = {'data': {}, 'provenance': {}, 'fields': [], 'warnings': []}
        merge_research(result, research())
        self.apply(self.job(result))
        self.assertEqual(self.machine.data['estimated_year_from'], '1996')
        self.assertEqual(self.machine.data['estimated_year_to'], '2002')
        self.assertNotIn('year', self.machine.data)
        self.assertIn('Año aproximado: 1996–2002 (por confirmar)', self.machine.data['description'])
        snap = {'data': self.machine.data, 'provenance': self.machine.provenance,
                'web_research': web_research_for_provenance(self.machine.provenance)}
        self.assertEqual({r['field'] for r in public_web_references(snap)}, set(AGE_LABELS))
        snap['data'] = {**snap['data'], 'estimated_year_from': None, 'estimated_year_to': None}
        self.assertEqual(public_web_references(snap), [])

    def test_partial_documented_period_cannot_mix_with_visual_range(self):
        from portal.research import merge_research
        from portal.tests.test_model_year_period import research
        self.edit(model='14H')
        result = {'data': {}, 'provenance': {}, 'fields': [], 'warnings': []}
        merge_research(result, research())
        result['data'].pop('estimated_year_to')
        self.apply(self.job(result))
        self.assertFalse(AGE_LABELS.keys() & self.machine.data.keys())

    def test_known_year_keeps_documented_model_period_out_of_unit_fields(self):
        from portal.research import merge_research
        from portal.tests.test_model_year_period import research
        self.edit(model='14H', year=1999)
        result = {'data': {}, 'provenance': {}, 'fields': [], 'warnings': []}
        merge_research(result, research())
        self.apply(self.job(result))
        self.assertFalse(AGE_LABELS.keys() & self.machine.data.keys())
        self.assertEqual(self.machine.data['year'], 1999)
