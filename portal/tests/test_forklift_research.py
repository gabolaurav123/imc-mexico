"""Literal seller specifications, family routing and exact-unit isolation."""
from unittest.mock import patch

from django.test import SimpleTestCase

from portal.research import normalize_direct_fields, is_validated_web_field
from portal.research_catalogs import parse_catalog_html
from portal.research_fetch import CatalogFetchError, fetch_catalog_html, supports_catalog_url
from portal.research_pipeline import _stage_request
from portal.research_sources import lookup_brand, source_kind


URL = 'https://www.smithmachinery.com/listing/example-forklift-model-xe20-s-n-test-0123/'
IDENTITY = {'brand': 'Caterpillar', 'model': 'XE20', 'serial': 'TEST-0123'}
LINES = (
    'CAPACITY --------------------- 4000 LBS',
    'LIFT HEIGHT ------------------ 180 in',
    'BATTERIES -------------------- 48V',
    'TRUCK WEIGHT W/O BATTERIES --- 6000 LBS',
    'TRUCK WEIGHT WITH BATTERIES -- 9000 LBS',
    'MIN/MAX BATTERY WEIGHT ------- 2800 LBS / 3100 LBS',
    'AMP HOUR CAPACITY ------------ 1200',
)


def document(*, brand='CATERPILLAR', model='XE20', serial='TEST-0123', lines=LINES, extra=''):
    # The structure and separators reflect Smith's public HTML, not fixture data
    # embedded in the implementation. Deliberately use different model/figures.
    heading = f'1 - PREOWNED CAT FORKLIFT, MODEL #: {model}, S/N: {serial}'
    return f'''<html><head><title>{heading} - Smith Machinery</title></head><body>
        <section class="single-listing"><h2 class="fill">{heading}</h2>
        <p><b>Brand</b><br><a>{brand}</a></p><p><b>Model</b><br>{model}</p>
        <p><b>Type</b><br>Forklift Trucks</p><p><b>Condition</b><br>Used</p>
        <p><b>Year</b><br>1998</p></section>
        <section class="single-listing"><div id="home"><div class="table-responsive">
        <h2>Equipped With</h2><div><strong>SPECIFICATIONS:</strong><br>
        {'<br>'.join(lines)}<br><strong>EQUIPPED WITH:</strong><br>BATTERIES<br>42 in FORKS<br>
        <strong>NOTES:</strong><br>SPECIFICATIONS SUBJECT TO VERIFICATION<br>
        <strong>DELIVERY:</strong><br>IMMEDIATE, SUBJECT TO PRIOR SALE</div></div></div></section>
        {extra}<footer>Seller: Ames, Iowa. Manufacturer office: Houston, Texas.</footer></body></html>'''


class ForkliftSourceTests(SimpleTestCase):
    def test_category_routes_cat_forklifts_without_reclassifying_construction(self):
        domains = lookup_brand('CAT', 'Montacargas').manufacturer_domains
        self.assertEqual(domains, ('logisnextamericas.com', 'catlifttruck.com'))
        self.assertEqual(lookup_brand('CAT', 'Excavadoras').manufacturer_domains, ('cat.com',))
        self.assertEqual(lookup_brand('CAT').manufacturer_domains, ('cat.com',))
        self.assertIsNone(lookup_brand('CAT XE20', 'Montacargas'))
        self.assertIsNone(lookup_brand('Unknown', 'Montacargas'))
        request, actual = _stage_request(IDENTITY, 'manufacturer', {'data': {}}, 'Montacargas')
        self.assertEqual(actual, list(domains))
        self.assertIn('montacargas forklift', request['query'])
        self.assertIn('Cat Lift Trucks', request['objective'])
        self.assertIsNone(request['identifiers']['serial'])
        request, catalogs = _stage_request(IDENTITY, 'catalogs', {'data': {}}, 'Montacargas')
        self.assertIn('machinetools.com', catalogs)
        self.assertNotIn('ritchiespecs.com', catalogs)
        self.assertEqual(source_kind('https://www.catlifttruck.com/product', 'CAT', 'Montacargas'), 'manufacturer')
        self.assertEqual(source_kind('https://www.cat.com/product', 'CAT', 'Montacargas'), 'public_documentation')
        self.assertEqual(source_kind('https://www.machinetools.com/en/models/example', 'CAT'), 'technical_catalog')

    def test_smith_routes_remain_retrieved_only_and_path_limited(self):
        for url in (URL, URL + '?utm_source=openai'):
            self.assertTrue(supports_catalog_url(url))
        for url in (URL.replace('/listing/', '/contact/'), URL + '?next=http://127.0.0.1',
                    URL.replace('www.smithmachinery.com', 'www.smithmachinery.com.evil.example'),
                    URL.replace('/listing/', '/listing/../'), URL.replace('/listing/', '/listing/%2e%2e/'),
                    URL + 'private/extra/', URL.replace('https:', 'http:'), URL + '#fragment',
                    URL.replace('www.', 'user:password@www.')):
            with self.subTest(url=url):
                self.assertFalse(supports_catalog_url(url))
        with patch('portal.research_fetch._resolve_public_ip') as dns:
            with self.assertRaisesMessage(CatalogFetchError, 'not_retrieved'):
                fetch_catalog_html(URL, retrieved_urls=[])
            dns.assert_not_called()


class ForkliftParserTests(SimpleTestCase):
    def parse(self, html=None, identity=None):
        return parse_catalog_html(html or document(), URL, identity or IDENTITY)

    def test_seven_fields_preserve_unit_identity_qualifiers_and_verification_note(self):
        parsed = self.parse()
        self.assertEqual(parsed['status'], 'matched')
        fields = {f.key: f for f in parsed['fields']}
        self.assertEqual(set(fields), {'capacity', 'lift_height', 'voltage', 'weight', 'battery_weight', 'battery_capacity', 'fork_length'})
        self.assertEqual(fields['capacity'].value, '4000 LBS')
        self.assertEqual(fields['lift_height'].value, '180 in')
        self.assertEqual(fields['voltage'].value, '48V')
        self.assertEqual(fields['weight'].value, 'TRUCK WEIGHT W/O BATTERIES: 6000 LBS; TRUCK WEIGHT WITH BATTERIES: 9000 LBS')
        self.assertEqual(fields['battery_capacity'].value, 'AMP HOUR CAPACITY: 1200')
        self.assertEqual(fields['battery_weight'].value, 'MIN/MAX BATTERY WEIGHT: 2800 LBS / 3100 LBS')
        self.assertEqual(fields['fork_length'].value, '42 in FORKS')
        for field in fields.values():
            self.assertEqual(field.scope, 'exact_serial')
            self.assertEqual(field.matched_serial, IDENTITY['serial'])
            self.assertIn('S/N: TEST-0123', field.evidence)
            self.assertIn('SPECIFICATIONS SUBJECT TO VERIFICATION', field.evidence)
            self.assertLessEqual(len(field.evidence), 650)
            self.assertNotIn('\n', field.value)
            self.assertNotIn('Houston', field.evidence)
            self.assertNotIn('IMMEDIATE', field.evidence)
        self.assertFalse({'country_of_origin', 'location', 'condition', 'year', 'manufacturer_address'} & set(fields))
        self.assertIn('TRUCK WEIGHT W/O BATTERIES --- 6000 LBS', fields['weight'].evidence)
        self.assertIn('TRUCK WEIGHT WITH BATTERIES -- 9000 LBS', fields['weight'].evidence)

    def test_seller_unit_is_never_used_as_model_reference_for_other_or_missing_serial(self):
        for changes in ({'serial': None}, {'serial': ''}, {'serial': 'TEST-012'}, {'serial': 'TEST-01234'},
                        {'serial': 'OTHER-0123'}, {'model': 'XE20 IT'}, {'brand': 'Komatsu'}):
            with self.subTest(changes=changes):
                parsed = self.parse(identity={**IDENTITY, **changes})
                self.assertEqual(parsed['status'], 'identity_mismatch')
                self.assertEqual(parsed['fields'], [])

    def test_header_model_and_structured_attributes_must_agree(self):
        for html in (document().replace('<br>XE20</p>', '<br>XE20 IT</p>'),
                     document().replace('<a>CATERPILLAR</a>', '<a>KOMATSU</a>'),
                     document().replace('S/N: TEST-0123', 'S/N: TEST-01234'),
                     document().replace('Forklift Trucks', 'Wheel Loaders')):
            with self.subTest(html=html[:80]):
                self.assertEqual(self.parse(html)['fields'], [])

    def test_missing_units_conflicting_duplicate_and_hidden_values_do_not_fill(self):
        lines = tuple(line.replace('4000 LBS', '4000').replace('48V', '48') for line in LINES)
        lines += ('LIFT HEIGHT ---- 170 in',)
        parsed = self.parse(document(lines=lines, extra='<div id="other">CAPACITY --- 9000 LBS</div>'))
        self.assertEqual(set(parsed['conflicting_fields']), {'lift_height'})
        self.assertFalse({'capacity', 'voltage', 'lift_height'} & {f.key for f in parsed['fields']})
        hidden = document().replace('4000 LBS', '<span hidden>9900 LBS</span>4000 LBS')
        capacity = next(f for f in self.parse(hidden)['fields'] if f.key == 'capacity')
        self.assertEqual(capacity.value, '4000 LBS')
        self.assertNotIn('9900', capacity.evidence)

    def test_fields_pass_normalizer_and_signed_provenance_without_another_llm(self):
        parsed = self.parse()
        fields = parsed['fields']
        passages = [{'passage_index': i, 'source_url': URL, 'source_title': parsed['title'],
                     'text': f.evidence, 'origin': 'direct_document'} for i, f in enumerate(fields)]
        result = normalize_direct_fields(IDENTITY, 'exact_serial', [{'url': URL, 'title': parsed['title']}],
            '\n\n'.join(p['text'] for p in passages), passages, {URL: parsed['title']}, direct_fields=fields)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['fields']), 7)
        self.assertEqual(result['diagnostics']['rejection_counts'], {})
        self.assertEqual(result['diagnostics']['llm_candidate_count'], 0)
        for field in result['fields']:
            meta = {'source': 'web', 'review': 'needs_review', 'scope': field['scope'],
                    'source_url': field['source_url'], 'source_title': field['source_title'],
                    'source_date': field['source_date'], 'evidence': field['evidence']}
            self.assertTrue(is_validated_web_field({'research': result}, field['key'], field['value'], meta))
