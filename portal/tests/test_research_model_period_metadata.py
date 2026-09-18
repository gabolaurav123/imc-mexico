"""Offline replay of actual v23 catalogue metadata; no HTTP, DB or provider."""
from copy import deepcopy

from django.core import signing
from django.test import SimpleTestCase
from django.utils import timezone

from portal.research import (MODEL_YEAR_KEYS, SIGNING_SALT, ResearchExtraction, ResearchField,
    _manifest, is_validated_web_field, merge_research, normalize_research, validated_model_period_fields)
from portal.research_model_periods import PERIOD_ORIGIN


IDENTITY = {'brand': 'CAT', 'model': '14H', 'serial': None}
SOURCES = [
    {'url': 'https://www.lectura-specs.com/en/model/construction-machinery/graders-caterpillar/14h-13775?utm_source=openai',
     'title': 'Caterpillar 14H Specifications & Technical Data (1996-2002) | LECTURA Specs'},
    {'url': 'https://www.lectura-specs.com/en/model/construction-machinery/graders-caterpillar/14h-1005586?utm_source=openai',
     'title': 'Caterpillar 14H Specifications & Technical Data (2003-2007) | LECTURA Specs'},
]


def normalize(sources=None, identity=None, titles=None, fields=()):
    sources = deepcopy(SOURCES if sources is None else sources)
    titles = {item['url']: item['title'] for item in sources} if titles is None else titles
    citations = {}
    for item in fields:
        citations.setdefault(item.source_url, []).append(item.evidence)
    return normalize_research(ResearchExtraction(fields=list(fields)), identity or IDENTITY, 'model', sources,
        '\n\n'.join(item.evidence for item in fields), citations=citations, source_titles=titles)


def meta(field):
    return {'source': 'web', 'review': 'needs_review', **{key: field[key] for key in
        ('scope', 'source_url', 'source_title', 'source_date', 'evidence')}}


class CatalogueMetadataPeriodTests(SimpleTestCase):
    def test_real_v23_sources_replay_without_body_or_provider(self):
        research = normalize()
        self.assertEqual(research['status'], 'completed')
        self.assertEqual(research['match'], 'model')
        self.assertEqual(research['sources'], SOURCES)
        fields = {field['key']: field for field in research['fields']}
        self.assertEqual(set(fields), MODEL_YEAR_KEYS)
        self.assertEqual(fields['estimated_year_from']['value'], '1996')
        self.assertEqual(fields['estimated_year_to']['value'], '2007')
        self.assertIn('1996–2002, 2003–2007', fields['estimated_year_basis']['value'])
        self.assertIn('año de esta unidad por confirmar', fields['estimated_year_basis']['value'])
        for field in fields.values():
            self.assertEqual(field['period_origin'], PERIOD_ORIGIN)
            self.assertEqual(len(field['period_records']), 2)
            self.assertIn('títulos recuperados', field['evidence'])
            self.assertNotIn('Fragmento citado:', field['evidence'])
            self.assertIsNone(field['matched_serial'])
            self.assertFalse(field['authority_validated'])
            self.assertTrue(is_validated_web_field({'research': research}, field['key'], field['value'], meta(field)))

    def test_metadata_requires_matching_server_retrieval_title_map(self):
        self.assertEqual(normalize(titles={})['fields'], [])
        self.assertEqual(normalize(titles={source['url']: 'Generated title' for source in SOURCES})['fields'], [])

    def test_brand_alias_is_allowed_but_variant_and_shared_title_are_not(self):
        for brand in ('CAT', 'Caterpillar'):
            self.assertEqual(len(normalize(identity={**IDENTITY, 'brand': brand})['fields']), 3)
        for title_identity, identity in (
            ('Caterpillar 14H IT', IDENTITY), ('Caterpillar 14H/14H IT', IDENTITY),
            ('Caterpillar 14H', {**IDENTITY, 'model': '14H IT'}),
            ('Komatsu 14H', IDENTITY), ('Caterpillar 14H2', IDENTITY),
        ):
            sources = [{**SOURCES[0], 'title': SOURCES[0]['title'].replace('Caterpillar 14H', title_identity)}]
            with self.subTest(title_identity=title_identity, identity=identity):
                self.assertEqual(normalize(sources, identity=identity)['fields'], [])

    def test_exact_variant_has_its_own_model_path_and_title(self):
        source = {'url': SOURCES[0]['url'].replace('14h-13775', '420f2-it-13775'),
                  'title': SOURCES[0]['title'].replace('14H', '420F2 IT')}
        self.assertEqual(len(normalize([source], identity={**IDENTITY, 'model': '420F2 IT'})['fields']), 3)

    def test_unrelated_lookalike_domain_and_wrong_model_path_rejected(self):
        base = SOURCES[0]['url']
        for url in (base.replace('www.lectura-specs.com', 'other.com'),
                    base.replace('www.lectura-specs.com', 'www.lectura-specs.com.evil.test'),
                    base.replace('/en/model/', '/en/news/'), base.replace('14h-13775', '14h-it-13775'),
                    base.replace('graders-caterpillar', 'graders-komatsu'), base.replace('/en/', '/de/'),
                    base.replace('https:', 'http:'), base + '&model=14H', base + '#1996',
                    base.replace('www.lectura-specs.com', 'user@www.lectura-specs.com')):
            with self.subTest(url=url):
                self.assertEqual(normalize([{**SOURCES[0], 'url': url}])['fields'], [])

    def test_dates_require_catalogue_title_pattern_not_publication_or_sale(self):
        for title in ('Caterpillar 14H published 1996-2002 | LECTURA Specs',
                      'Caterpillar 14H for sale (1996-2002) | LECTURA Specs',
                      'Caterpillar 14H Specifications & Technical Data (1996) | LECTURA Specs',
                      SOURCES[0]['title'] + ' Updated in 2026',
                      SOURCES[0]['title'].replace('1996-2002', '2002-1996'),
                      SOURCES[0]['title'].replace('1996-2002', '1899-1901'),
                      SOURCES[0]['title'].replace('1996-2002', f'1996-{timezone.now().year + 1}')):
            with self.subTest(title=title):
                self.assertEqual(normalize([{**SOURCES[0], 'title': title}])['fields'], [])

    def test_contiguous_or_overlap_accepted_gap_not_filled(self):
        for period in ('2002-2007', '2003-2007', '1998-2007'):
            sources = [SOURCES[0], {**SOURCES[1], 'title': SOURCES[1]['title'].replace('2003-2007', period)}]
            with self.subTest(period=period):
                fields = {f['key']: f['value'] for f in normalize(sources)['fields']}
                self.assertEqual((fields['estimated_year_from'], fields['estimated_year_to']), ('1996', '2007'))
        sources = [SOURCES[0], {**SOURCES[1], 'title': SOURCES[1]['title'].replace('2003-2007', '2004-2007')}]
        self.assertEqual(normalize(sources)['fields'], [])

    def test_no_silent_truncation_and_conflicting_duplicate_metadata_veto(self):
        sources = [{**SOURCES[0], 'url': SOURCES[0]['url'].replace('13775', str(13775 + index))} for index in range(5)]
        self.assertEqual(normalize(sources)['fields'], [])
        duplicate = {**SOURCES[0], 'url': SOURCES[0]['url'].split('?')[0],
                     'title': SOURCES[0]['title'].replace('1996-2002', '1997-2003')}
        self.assertEqual(normalize([SOURCES[0], duplicate])['fields'], [])

    def test_proof_tampering_and_resigned_inconsistent_semantics_are_rejected(self):
        original = normalize()
        tampered = deepcopy(original)
        tampered['fields'][0]['value'] = '1995'
        field = tampered['fields'][0]
        self.assertFalse(is_validated_web_field({'research': tampered}, field['key'], field['value'], meta(field)))
        mutations = [lambda r: r['fields'][0].update(value='1995'),
                     lambda r: r['fields'][2].update(value='Año exacto de esta unidad 1996'),
                     lambda r: r['fields'][1].update(scope='exact_serial'),
                     lambda r: r['fields'][0]['period_records'][1].update(end_year='2008'),
                     lambda r: r['fields'][0]['period_records'].pop(),
                     lambda r: r['sources'].pop(),
                     lambda r: r['identity'].update(model='14H IT'),
                     lambda r: r['fields'][0].update(period_origin='generic_title_date'),
                     lambda r: r['fields'][0].update(evidence='Years of manufacture: 1996-2007')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                research = deepcopy(original)
                mutate(research)
                research['proof'] = signing.Signer(salt=SIGNING_SALT).sign_object(_manifest(research), compress=True)
                self.assertEqual(validated_model_period_fields(research), {})
                for field in research['fields']:
                    self.assertFalse(is_validated_web_field({'research': research}, field['key'], field['value'], meta(field)))

    def test_separate_documentary_contradiction_is_not_overridden(self):
        url = 'https://www.cat.com/catalogue/14h'
        evidence = 'Caterpillar 14H: Production years: 1995–2001.'
        field = ResearchField(key='estimated_year_from', value='1995', scope='model', source_url=url,
            evidence=evidence, matched_brand='Caterpillar', matched_model='14H', matched_serial=None)
        value = normalize([*SOURCES, {'url': url, 'title': 'Caterpillar 14H'}], fields=[field])
        self.assertEqual(value['fields'], [])
        self.assertIn('conflicting_model_periods', value['diagnostics']['rejection_counts'])

    def test_explicit_bodies_for_same_catalogue_records_can_keep_combined_coverage(self):
        fields = [ResearchField(key='estimated_year_from', value=start, scope='model', source_url=source['url'],
            evidence=f'Caterpillar 14H: Years of manufacture: {start}–{end}.',
            matched_brand='Caterpillar', matched_model='14H', matched_serial=None)
            for source, start, end in zip(SOURCES, ('1996', '2003'), ('2002', '2007'))]
        value = normalize(fields=fields)
        self.assertEqual({f['key']: f['value'] for f in value['fields']}['estimated_year_to'], '2007')

    def test_merge_preserves_typed_provenance_and_human_blank_group(self):
        result = {'data': {}, 'provenance': {}, 'fields': [], 'warnings': []}
        merge_research(result, normalize())
        self.assertNotIn('year', result['data'])
        for key in MODEL_YEAR_KEYS:
            self.assertEqual(result['provenance'][key]['period_origin'], PERIOD_ORIGIN)
            self.assertEqual(len(result['provenance'][key]['period_records']), 2)
        result = {'data': {}, 'provenance': {}, 'fields': [], 'warnings': []}
        merge_research(result, normalize(), {'data': {'estimated_year_from': None},
            'provenance': {'estimated_year_from': {'source': 'user', 'review': 'confirmed'}}})
        self.assertEqual(result['data'], {})
