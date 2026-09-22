from io import StringIO
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from portal.knowledge import research_from_knowledge, retrieve_technical_references
from portal.knowledge_catalogue import KNOWLEDGE_ROOT, bundled_records
from portal.models import Brand, Category, EquipmentModel, Machine, TechnicalReference
from portal.structured_data import normalize_structured_data


class BundledKnowledgeTests(TestCase):
    def seed(self):
        call_command('seed', stdout=StringIO())

    def snapshot_for(self, reference):
        return {'data': {'brand': reference.brand, 'model': reference.model, 'variant': reference.variant,
                         'generation': reference.generation, 'location_country': reference.market},
                'provenance': {'variant': {'source': 'user'}, 'location_country': {'source': 'user'}}}

    def test_bundle_creates_real_linked_rows_without_listing_inventory(self):
        self.seed()
        self.assertFalse(Machine.objects.exists())
        self.assertEqual(TechnicalReference.objects.count(), len(bundled_records()))
        for reference in TechnicalReference.objects.select_related('equipment_model__brand'):
            with self.subTest(model=str(reference)):
                self.assertIsNotNone(reference.equipment_model_id)
                self.assertEqual(reference.equipment_model.category_id, reference.category_id)
                self.assertEqual(reference.equipment_model.name, reference.model)
                self.assertEqual(reference.equipment_model.brand.name, reference.brand)
                self.assertTrue(reference.active)
                self.assertEqual(reference.review, 'approved')

    def test_each_curated_spec_survives_real_research_validation(self):
        self.seed()
        for reference in TechnicalReference.objects.all():
            with self.subTest(model=str(reference)):
                research = research_from_knowledge({}, self.snapshot_for(reference), reference.category)
                self.assertIsNotNone(research)
                fields = {field['key']: field for field in research['fields']}
                for key, spec in reference.specs.items():
                    self.assertIn(key, fields, (str(reference), research))
                    self.assertEqual(fields[key]['value'], str(spec['value']))
                    self.assertEqual(fields[key]['scope'], 'model')
                self.assertNotIn('year', fields)
                self.assertNotIn('country_of_origin', fields)

    def test_restart_does_not_duplicate_or_reactivate_staff_edits(self):
        self.seed()
        reference = TechnicalReference.objects.first()
        TechnicalReference.objects.filter(pk=reference.pk).update(active=False, specs={})
        counts = (TechnicalReference.objects.count(), EquipmentModel.objects.count(), Brand.objects.count())
        self.seed()
        reference.refresh_from_db()
        self.assertFalse(reference.active)
        self.assertEqual(reference.specs, {})
        self.assertEqual(counts, (TechnicalReference.objects.count(), EquipmentModel.objects.count(), Brand.objects.count()))

    def test_manual_import_is_linked_but_never_active(self):
        Category.objects.create(slug='excavadoras', name='Excavadoras')
        call_command('import_technical_knowledge', path=str(KNOWLEDGE_ROOT/'excavadoras'), stdout=StringIO())
        self.assertFalse(TechnicalReference.objects.filter(category__slug='excavadoras', active=True).exists())
        self.assertFalse(TechnicalReference.objects.filter(equipment_model__isnull=True).exists())
        self.seed()
        self.assertFalse(TechnicalReference.objects.filter(category__slug='excavadoras', active=True).exists())

    def test_modified_release_bundle_is_not_silently_approved(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'tampered.json').write_text(json.dumps({'references': []}))
            (root/'bundled.json').write_text(json.dumps({'files':[{'path':'tampered.json', 'sha256':'0'*64}]}))
            with self.assertRaises(CommandError):
                bundled_records(root)

    def test_malformed_import_rolls_back_without_invalid_catalogue_rows(self):
        Category.objects.create(slug='excavadoras', name='Excavadoras')
        for key, value in (('brand', ['Caterpillar']), ('provenance', []), ('period_from', '2003')):
            record = deepcopy(bundled_records()[0])
            record[key] = value
            with self.subTest(key=key), TemporaryDirectory() as directory:
                path = Path(directory)/'invalid.json'
                path.write_text(json.dumps({'references':[record]}), encoding='utf-8')
                with self.assertRaises(CommandError):
                    call_command('import_technical_knowledge', path=str(path), stdout=StringIO())
                self.assertFalse(TechnicalReference.objects.exists())
                self.assertFalse(Brand.objects.exists())

    def test_malformed_provenance_cannot_be_approved_through_admin_validation(self):
        self.seed()
        reference = TechnicalReference.objects.first()
        reference.provenance = []
        with self.assertRaises(ValidationError):
            reference.full_clean()

    def test_alias_and_spacing_match_without_matching_another_model(self):
        self.seed()
        reference = TechnicalReference.objects.get(brand='Caterpillar', model='320')
        snapshot = self.snapshot_for(reference)
        snapshot['data']['brand'] = 'CAT'
        snapshot['data']['model'] = '3 2 0'
        self.assertEqual(retrieve_technical_references(snapshot, reference.category), [reference])
        snapshot['data']['model'] = '320D'
        self.assertFalse(retrieve_technical_references(snapshot, reference.category))

    def test_disabled_catalogue_and_incompatible_model_period_are_excluded(self):
        self.seed()
        reference = TechnicalReference.objects.first()
        reference.period_from, reference.period_to = 2000, 2005
        reference.save()
        snapshot = self.snapshot_for(reference)
        snapshot['data']['year'] = 2018
        snapshot['provenance']['year'] = {'source':'user'}
        self.assertFalse(retrieve_technical_references(snapshot, reference.category))
        snapshot['data']['year'] = 2003
        self.assertEqual(retrieve_technical_references(snapshot, reference.category), [reference])
        EquipmentModel.objects.filter(pk=reference.equipment_model_id).update(active=False)
        self.assertFalse(retrieve_technical_references(snapshot, reference.category))

    def test_relation_cannot_point_to_another_machine_family(self):
        self.seed()
        reference = TechnicalReference.objects.first()
        wrong = EquipmentModel.objects.exclude(category=reference.category).first()
        self.assertIsNotNone(wrong)
        reference.equipment_model = wrong
        with self.assertRaises(ValidationError):
            reference.full_clean()

    def test_archived_model_can_propose_period_without_borrowing_2009_specs(self):
        self.seed()
        category = Category.objects.get(slug='excavadoras')
        snapshot = {'data': {'brand': 'Volvo', 'model': 'EC210B', 'location_country': 'México'},
                    'provenance': {'location_country': {'source': 'user'}}}
        result = research_from_knowledge({}, snapshot, category)
        fields = {field['key']: field['value'] for field in result['fields']}
        self.assertEqual(fields['estimated_year_from'], '2003')
        self.assertEqual(fields['estimated_year_to'], '2009')
        self.assertNotIn('year', fields)
        self.assertNotIn('weight', fields)
        self.assertNotIn('power', fields)
        self.assertNotIn('country_of_origin', fields)

    def test_cat_320d_l_catalogue_period_matches_without_variant_or_market(self):
        self.seed()
        category = Category.objects.get(slug='excavadoras')
        snapshot = {'data': {'brand': 'Caterpillar', 'model': '320D L'}, 'provenance': {}}
        result = research_from_knowledge({}, snapshot, category)
        fields = {field['key']: field['value'] for field in result['fields']}
        self.assertEqual(fields['estimated_year_from'], '2006')
        self.assertEqual(fields['estimated_year_to'], '2014')
        self.assertNotIn('year', fields)

    def test_mixed_imperial_depth_is_numeric_but_configuration_ranges_are_not_invented(self):
        self.assertEqual(str(normalize_structured_data({'digging_depth':'18 ft 8 in'})['digging_depth_m']), '5.6896')
        self.assertIsNone(normalize_structured_data({'digging_depth':'18 ft 14 in'})['digging_depth_m'])
        values = normalize_structured_data({'weight':'24200-24800 kg', 'capacity':'0.50-1.41 m³'})
        self.assertIsNone(values['weight_kg'])
        self.assertIsNone(values['capacity_m3'])
