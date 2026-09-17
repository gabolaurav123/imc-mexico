"""Documented model production periods are separate from exact unit years."""
from copy import deepcopy

from django.core import signing
from django.test import SimpleTestCase
from django.utils import timezone

from portal.research import (MODEL_YEAR_KEYS, SIGNING_SALT, ResearchCandidate, ResearchCandidates,
    ResearchExtraction, ResearchField, _manifest, compose_description, documented_model_period,
    is_validated_web_field, merge_research, normalize_candidates, normalize_research,
    validated_model_period_fields)
from portal.research_pipeline import NORMALIZE_INSTRUCTIONS, SEARCH_INSTRUCTIONS, _stage_request


URL = 'https://www.cat.com/catalogue/14h'
IDENTITY = {'brand': 'Caterpillar', 'model': '14H', 'serial': None}
TEXT = 'Caterpillar 14H: Production years: 1996–2002.'


def field(key='estimated_year_from', value='1996', text=TEXT, url=URL, **changes):
    values = dict(key=key, value=value, scope='model', source_url=url, evidence=text,
                  matched_brand='Caterpillar', matched_model='14H', matched_serial=None)
    values.update(changes)
    return ResearchField(**values)


def research(fields=None, identity=None, sources=None, titles=None):
    fields = [field()] if fields is None else fields
    sources = sources or list({item.source_url: {'url': item.source_url, 'title': 'Caterpillar 14H'} for item in fields}.values())
    citations = {}
    for item in fields:
        citations.setdefault(item.source_url, []).append(item.evidence)
    return normalize_research(ResearchExtraction(fields=fields), identity or IDENTITY,
        'exact_serial' if (identity or IDENTITY).get('serial') else 'model', sources,
        '\n\n'.join(item.evidence for item in fields), citations=citations, source_titles=titles)


def meta(item):
    return {'source': 'web', 'review': 'needs_review', **{key: item[key] for key in
            ('scope', 'source_url', 'source_title', 'source_date', 'evidence')}}


class DocumentedModelPeriodTests(SimpleTestCase):
    def test_explicit_production_period_generates_complete_signed_trio_not_unit_year(self):
        value = research()
        fields = {f['key']: f for f in value['fields']}
        self.assertEqual(set(fields), MODEL_YEAR_KEYS)
        self.assertEqual(fields['estimated_year_from']['value'], '1996')
        self.assertEqual(fields['estimated_year_to']['value'], '2002')
        self.assertIn('año de esta unidad por confirmar', fields['estimated_year_basis']['value'])
        self.assertIn('www.cat.com', fields['estimated_year_basis']['value'])
        self.assertNotIn('year', fields)
        for item in fields.values():
            self.assertEqual(item['scope'], 'model')
            self.assertIsNone(item['matched_serial'])
            self.assertTrue(is_validated_web_field({'research': value}, item['key'], item['value'], meta(item)))
        self.assertEqual(set(validated_model_period_fields(value)), MODEL_YEAR_KEYS)

    def test_both_endpoints_and_local_explanation_are_not_three_distinct_proposals(self):
        value = research([field(), field('estimated_year_to', '2002'),
                          field('estimated_year_basis', 'Production years: 1996–2002')])
        self.assertEqual(len(value['fields']), 3)
        self.assertEqual(value['fields'][2]['value'],
            'Periodo documentado del modelo: 1996–2002; año de esta unidad por confirmar. Fuente: www.cat.com')

    def test_explicit_labels_supported_without_guessing_missing_endpoint(self):
        for text in ['Periodo de fabricación: 1996–2002', 'Años de producción: 1996 a 2002',
                     'Fabricado entre 1996 y 2002', 'Manufactured from 1996 until 2002',
                     'Produced between 1996 and 2002', 'Years of manufacture: 1996-2002',
                     'Baujahre 1996–2002', 'Années de production: 1996 à 2002']:
            with self.subTest(text=text):
                self.assertEqual(documented_model_period(text), ('1996', '2002'))

    def test_markdown_emphasis_is_parsed_without_changing_original_cited_evidence(self):
        for marker in ('**', '*', '__', '_', '***'):
            text = f'Caterpillar 14H: {marker}Production years{marker}: {marker}1996–2002{marker}.'
            with self.subTest(marker=marker):
                value = research([field(text=text)])
                self.assertEqual(len(value['fields']), 3)
                self.assertEqual({item['evidence'] for item in value['fields']}, {text})
                for item in value['fields']:
                    self.assertTrue(is_validated_web_field({'research': value}, item['key'], item['value'], meta(item)))
        for text in ['**Copyright**: **1996–2002**', '**Published**: 1996–2002',
                     '**Production years**: 2002–1996', '**Not manufactured**: 1996–2002']:
            with self.subTest(invalid=text):
                self.assertIsNone(documented_model_period(text))

    def test_copyright_sale_release_isolated_or_unlabelled_years_do_not_estimate(self):
        for text in ['Caterpillar 14H (1996–2002)', 'Copyright 1996–2002',
                     'Caterpillar 14H for sale: 1996–2002', 'Published 1996–2002',
                     'Introduced 1996; discontinued 2002', 'Production years: 1996',
                     'Manufactured since 1996', 'Produced 1996–present',
                     'Not manufactured from 1996 to 2002', 'Periodo de fabricación desconocido: 1996–2002']:
            with self.subTest(text=text):
                self.assertFalse(research([field(text='Caterpillar 14H. ' + text)])['fields'])
        self.assertIsNone(documented_model_period('Produced between 1996 and 2002 units'))
        for text in ['Factory built 1996–2002', 'Engine manufactured from 1996 to 2002',
                     'Manual production years 1996–2002', 'Años de producción del motor: 1996–2002']:
            with self.subTest(component=text):
                self.assertFalse(research([field(text='Caterpillar 14H. ' + text)])['fields'])

    def test_range_bounds_and_endpoint_value_are_enforced(self):
        for period in ['1899–2002', '2002–1996', f'1996–{timezone.now().year + 1}', '19960–2002']:
            with self.subTest(period=period):
                self.assertFalse(research([field(text='Caterpillar 14H. Production years: ' + period)])['fields'])
        self.assertFalse(research([field(value='2002')])['fields'])
        self.assertFalse(research([field('estimated_year_to', '1996')])['fields'])
        current = str(timezone.now().year)
        self.assertEqual(documented_model_period(f'Production years: 1900–{current}'), ('1900', current))
        self.assertEqual(documented_model_period('Caterpillar 14H motor grader manufactured from 1996 to 2002'), ('1996', '2002'))

    def test_model_identity_variant_literal_value_and_citation_guards_remain(self):
        for changes in [{'text': TEXT.replace('14H', '14H IT')}, {'matched_model': '14H IT'},
                        {'text': TEXT.replace('Caterpillar', 'Komatsu')}, {'matched_brand': 'Komatsu'},
                        {'value': '1997'}, {'url': 'https://www.scribd.com/document/123'}]:
            with self.subTest(changes=changes):
                self.assertFalse(research([field(**changes)])['fields'])
        item = field()
        value = normalize_research(ResearchExtraction(fields=[item]), IDENTITY, 'model',
            [{'url': URL, 'title': 'Caterpillar 14H'}], TEXT, citations={URL: ['Caterpillar 14H: Weight 2 t.']})
        self.assertFalse(value['fields'])

    def test_source_title_can_establish_identity_but_not_supply_production_years(self):
        title = 'Caterpillar 14H Production years 1996–2002'
        text = 'Year: 1996. Technical specifications.'
        self.assertFalse(research([field(text=text)], sources=[{'url': URL, 'title': title}], titles={URL: title})['fields'])
        text = 'Production years: 1996–2002.'
        value = research([field(text=text)], sources=[{'url': URL, 'title': 'Caterpillar 14H'}], titles={URL: 'Caterpillar 14H'})
        self.assertEqual(len(value['fields']), 3)
        self.assertTrue(validated_model_period_fields(value))

    def test_conflicting_model_periods_are_omitted_together(self):
        other = field(value='2003', text='Caterpillar 14H: Production years: 2003–2007.',
                      url='https://example.org/catalogue/14h')
        value = research([field(), other, field('power', '70 kW', 'Caterpillar 14H: Power 70 kW.')])
        self.assertEqual([item['key'] for item in value['fields']], ['power'])
        self.assertEqual(value['diagnostics']['rejection_counts']['conflicting_model_periods'], 2)

    def test_exact_serial_query_still_creates_only_model_period_and_keeps_year_rule(self):
        identity = {**IDENTITY, 'serial': 'UNIT1234'}
        text = 'Caterpillar 14H. S/N UNIT1234. Production years: 1996–2002.'
        value = research([field(text=text, scope='exact_serial', matched_serial='UNIT1234')], identity)
        self.assertEqual(len(value['fields']), 3)
        self.assertTrue(all(item['scope'] == 'model' and item['matched_serial'] is None for item in value['fields']))
        self.assertFalse(research([field('year', '1996')])['fields'])
        exact = research([field('year', '1999', 'Caterpillar 14H. S/N UNIT1234: year 1999.',
                              scope='exact_serial', matched_serial='UNIT1234')], identity)
        self.assertEqual(exact['fields'][0]['key'], 'year')

    def test_existing_candidate_pipeline_reuses_single_passage_no_new_provider(self):
        item = ResearchCandidate(key='estimated_year_to', value='2002', scope='model', passage_index=0,
            matched_brand='Caterpillar', matched_model='14H', matched_serial=None)
        value = normalize_candidates(ResearchCandidates(fields=[item]), IDENTITY, 'model',
            [{'url': URL, 'title': 'Caterpillar 14H'}], TEXT, [{'source_url': URL, 'text': TEXT}])
        self.assertEqual(len(value['fields']), 3)
        self.assertIn('periodo', SEARCH_INSTRUCTIONS)
        self.assertIn('estimated_year_from', NORMALIZE_INSTRUCTIONS)
        request, _ = _stage_request(IDENTITY, 'catalogs', {'data': {}}, 'Motoniveladoras')
        self.assertIn('estimated_year_from', request['priority_missing_fields'])
        self.assertIn('specifications production years', request['query'])
        self.assertIn('"14H"', request['query'])
        self.assertNotIn('production years', _stage_request(IDENTITY, 'manufacturer', {'data': {}})[0]['query'])

    def test_verifier_rejects_incomplete_or_incoherent_trio_even_if_signed(self):
        baseline = research()
        for change in ('missing', 'source', 'basis', 'unit_scope', 'year_value'):
            value = deepcopy(baseline)
            if change == 'missing': value['fields'].pop()
            elif change == 'source': value['fields'][0]['source_url'] = 'https://other.example.com/model'
            elif change == 'basis': value['fields'][2]['value'] = 'Año de fabricación confirmado: 1996'
            elif change == 'unit_scope':
                for item in value['fields']: item['scope'] = 'exact_serial'
            else: value['fields'][0]['value'] = '1997'
            value['proof'] = signing.Signer(salt=SIGNING_SALT).sign_object(_manifest(value))
            item = value['fields'][0]
            with self.subTest(change=change):
                self.assertFalse(is_validated_web_field({'research': value}, item['key'], item['value'], meta(item)))

    def test_merge_preserves_any_human_interval_member_even_blank_and_never_sets_year(self):
        for key in MODEL_YEAR_KEYS:
            result = {'data': {}, 'provenance': {}, 'fields': [], 'warnings': []}
            snapshot = {'data': {key: None}, 'provenance': {key: {'source': 'user', 'review': 'confirmed'}}}
            with self.subTest(key=key):
                merge_research(result, research(), snapshot)
                self.assertFalse(MODEL_YEAR_KEYS.intersection(result['data']))
        result = {'data': {}, 'provenance': {}, 'fields': [], 'warnings': []}
        merge_research(result, research())
        self.assertEqual(MODEL_YEAR_KEYS, set(result['data']))
        self.assertNotIn('year', result['data'])

    def test_description_keeps_approximate_label_after_human_confirmation_or_single_bound(self):
        values = {'estimated_year_from': '1996', 'estimated_year_to': '2002',
                  'estimated_year_basis': 'Periodo documentado del modelo; año de esta unidad por confirmar'}
        provenance = {key: {'source': 'user', 'review': 'confirmed'} for key in values}
        text = compose_description(values, provenance, 'Motoniveladoras')
        self.assertIn('Año aproximado: 1996–2002 (por confirmar).', text)
        self.assertIn(values['estimated_year_basis'], text)
        self.assertNotIn('año: 1996', text)
        values.pop('estimated_year_to')
        self.assertIn('Año aproximado: desde 1996 (por confirmar).', compose_description(values, provenance))
        values['estimated_year_from'], values['estimated_year_to'] = '2002', '1996'
        self.assertNotIn('Año aproximado:', compose_description(values, provenance))
