import json
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from portal.category_profiles import IMC_TYPE_TAXONOMY, category_catalog, normalized_alias
from portal.knowledge import research_from_knowledge, retrieve_technical_references
from portal.knowledge_catalogue import KNOWLEDGE_ROOT, bundled_records
from portal.models import Category, Machine, TechnicalReference
from portal.services import DATA_FIELDS


class ExpandedArchiveReleaseTests(SimpleTestCase):
    def test_release_has_literal_manufacturer_rows_without_unit_or_price_claims(self):
        records = json.loads((KNOWLEDGE_ROOT / 'catalogo_historico_volvo_2026-09-25.json').read_text(encoding='utf-8'))['references']
        self.assertGreaterEqual(len(records), 400)
        self.assertGreaterEqual(sum(bool(item.get('period_from')) for item in records), 350)
        identities = set()
        for item in records:
            with self.subTest(model=item['model']):
                self.assertTrue(item['source'].startswith('https://www.volvoce.com/global/en/products-and-services/past-products/'))
                identity = (item['category_slug'], item['brand'], item['model'], item['variant'])
                self.assertNotIn(identity, identities)
                identities.add(identity)
                self.assertLessEqual(set(item['specs']), DATA_FIELDS)
                self.assertFalse({'year', 'serial', 'hours', 'price', 'estimated_price_min', 'country_of_origin', 'location'} & item['specs'].keys())
                self.assertTrue(item['specs'] or item.get('period_from'))
                for spec in item['specs'].values():
                    self.assertIn(spec['source_value'], spec['evidence'])
                    self.assertIn(spec['value'], spec['evidence'])
        # A copied table on Volvo's EW160D page actually labels EW180D;
        # excluding it prevents silently assigning another model's data.
        self.assertFalse(any(item['source'].endswith('/ew160d/') for item in records))
        self.assertTrue(any(item['source'].endswith('/ew180d/') for item in records))
        release_sources = {item['source'] for item in bundled_records()}
        self.assertLessEqual({item['source'] for item in records}, release_sources)

    def test_taxonomy_covers_imc_construction_types_without_fabricating_inventory(self):
        mapped = [label for item in IMC_TYPE_TAXONOMY['types'] for label in item['imc_types']]
        self.assertEqual(len(mapped), len(set(mapped)))
        for label in ('EXCAVADORAS HIDRAULICAS', 'COMPACTADORA CON LLANTAS', 'BOMBAS PARA CONCRETO',
                      'CARGADORAS SOBRE ORUGAS', 'PLATAFORMA TIPO TIJERA', 'TIENDE TUBOS'):
            self.assertIn(label, mapped)
        self.assertNotIn('OFERTA ESPECIAL', mapped)
        self.assertEqual(len(IMC_TYPE_TAXONOMY['types']), 44)


class ExpandedArchiveRetrievalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed', stdout=StringIO())

    def test_documented_period_is_available_without_a_location_or_exact_unit_year(self):
        snapshot = {'data': {'brand': 'Volvo', 'model': 'EC210C'}, 'provenance': {}}
        result = research_from_knowledge({}, snapshot, Category.objects.get(slug='excavadoras'))
        fields = {field['key']: field['value'] for field in result['fields']}
        self.assertEqual(fields['estimated_year_from'], '2007')
        self.assertEqual(fields['estimated_year_to'], '2013')
        self.assertNotIn('year', fields)
        self.assertNotIn('price', fields)
        self.assertFalse(Machine.objects.exists())

    def test_brochure_snapshot_date_does_not_turn_into_a_production_period(self):
        reference = TechnicalReference.objects.get(brand='Volvo', model='SD115')
        self.assertIn('2016 specifications', reference.source_version)
        self.assertIsNone(reference.period_from)
        self.assertIsNone(reference.period_to)

    def test_engine_variants_remain_separate_when_retrieving_a_model(self):
        category = Category.objects.get(slug='camiones')
        snapshot = {'data': {'brand': 'Volvo', 'model': 'A25D 6x6'}, 'provenance': {}}
        self.assertEqual(retrieve_technical_references(snapshot, category), [])
        snapshot['data']['variant'] = 'with D9 engine'
        snapshot['provenance']['variant'] = {'source': 'user'}
        references = retrieve_technical_references(snapshot, category)
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0].specs['engine']['value'], 'Volvo D9B AB E3')

    def test_typeahead_resolves_imc_names_to_the_canonical_research_family(self):
        options = category_catalog(Category.objects.filter(active=True))
        for query, slug in [('EXCAVADORA SOBRE RUEDAS', 'excavadoras'), ('COMPACTADORA DE DOBLE RODILLO', 'compactadores'),
                            ('SCREPERS', 'mototraillas'), ('BOMBAS PARA CONCRETO', 'bombas-concreto')]:
            matches = [item for item in options if normalized_alias(query) in {normalized_alias(alias) for alias in item['aliases']}]
            self.assertEqual([item['slug'] for item in matches], [slug])
