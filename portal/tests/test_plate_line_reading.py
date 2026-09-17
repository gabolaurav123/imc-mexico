"""Plate-line coverage and literal field preservation; no real provider calls."""
from django.test import SimpleTestCase

from portal.processing import AI_KEYS, MachineAnalysis, normalize_analysis, plate_serial_is_clear


ASSET = 'test-machine-plate'


def extracted(key, value, *, evidence=None, review='clear'):
    return {'key': key, 'label': key, 'value': value, 'source': 'plate',
            'review': review, 'asset_id': ASSET, 'component': 'machine',
            'evidence': evidence if evidence is not None else f'{key}: {value}'}


def analysis(fields, transcription, *, readability='clear'):
    return MachineAnalysis(title='Montacargas de prueba', description='', category='Montacargas',
        fields=fields, plates=[{'asset_id': ASSET, 'component': 'machine',
                               'transcription': transcription, 'readability': readability}],
        warnings=[], questions=[], image_observations=[{'asset_id': ASSET, 'kind': 'plate'}])


class PlateLineReadingTests(SimpleTestCase):
    def test_forklift_lines_keep_literal_units_and_component_qualifiers(self):
        values = {
            'front_tire_size': '20X8X16', 'rear_tire_size': '15X5X11.5',
            'mast_tilt': 'MAX REARWARD 7 deg.', 'load_tire_tread': '35.5 in.',
            'manufacturer': 'EXAMPLE FORKLIFT CO.', 'manufacturer_address': 'Example City, USA',
            'voltage': '48 V', 'lift_height': '190 in.', 'load_center': '24 in.',
            'battery_weight': 'MIN 900 lb', 'battery_capacity': '600 Ah', 'fork_length': '42 in.',
        }
        self.assertTrue(values.keys() <= AI_KEYS)
        fields = [extracted(key, value) for key, value in values.items()]
        result = normalize_analysis(analysis(fields, '\n'.join(item['evidence'] for item in fields)), [ASSET])
        for key, value in values.items():
            with self.subTest(key=key):
                self.assertEqual(result['data'][key], value)
                self.assertEqual(result['provenance'][key]['asset_id'], ASSET)
                self.assertEqual(result['provenance'][key]['source'], 'plate')
                self.assertEqual(result['provenance'][key]['review'], 'clear')
        self.assertNotIn('location', result['data'])
        self.assertNotIn('country_of_origin', result['data'])
        self.assertNotIn('year', result['data'])

    def test_manufacturer_address_survives_without_becoming_manufacturing_origin(self):
        fields = [extracted('manufacturer', 'EXAMPLE FORKLIFT CO.'),
                  extracted('manufacturer_address', 'Example City, USA'),
                  extracted('country_of_origin', 'USA', evidence='EXAMPLE FORKLIFT CO. Example City, USA')]
        result = normalize_analysis(analysis(fields, '\n'.join(item['evidence'] for item in fields)), [ASSET])
        self.assertEqual(result['data']['manufacturer_address'], 'Example City, USA')
        self.assertIsNone(result['data']['country_of_origin'])
        self.assertEqual(result['provenance']['country_of_origin']['review'], 'needs_review')
        self.assertNotIn('location', result['data'])

    def test_component_plate_fields_cannot_become_machine_specifications(self):
        fields = [extracted('voltage', '24 V'), extracted('manufacturer', 'COMPONENT CO.')]
        parsed = analysis(fields, 'Voltage: 24 V\nCOMPONENT CO.')
        parsed.plates[0].component = 'engine'
        for field in parsed.fields:
            field.component = 'engine'
        result = normalize_analysis(parsed, [ASSET])
        self.assertNotIn('voltage', result['data'])
        self.assertNotIn('manufacturer', result['data'])

    def test_commercial_brand_and_legal_manufacturer_stay_distinct_and_missing_footer_is_not_inferred(self):
        fields = [extracted('brand', 'EXAMPLE'),
                  extracted('manufacturer', 'INDUSTRIAL EQUIPMENT COMPANY LTD.'),
                  extracted('manufacturer_address', 'Example City, USA'),
                  extracted('mast_tilt', 'MAX REARWARD 7 deg.',
                            evidence='MAST TILT MAX REARWARD 7 deg.')]
        result = normalize_analysis(analysis(fields, '\n'.join(item['evidence'] for item in fields)), [ASSET])
        self.assertEqual(result['data']['brand'], 'EXAMPLE')
        self.assertEqual(result['data']['manufacturer'], 'INDUSTRIAL EQUIPMENT COMPANY LTD.')
        self.assertEqual(result['data']['manufacturer_address'], 'Example City, USA')
        self.assertEqual(result['data']['mast_tilt'], 'MAX REARWARD 7 deg.')
        missing = [extracted('brand', 'EXAMPLE'),
                   extracted('manufacturer', None, review='needs_review', evidence=''),
                   extracted('manufacturer_address', None, review='needs_review', evidence='')]
        result = normalize_analysis(analysis(missing, 'EXAMPLE'), [ASSET])
        self.assertIsNone(result['data']['manufacturer'])
        self.assertIsNone(result['data']['manufacturer_address'])
        self.assertNotIn('country_of_origin', result['data'])
        self.assertNotIn('location', result['data'])

    def test_clear_serial_line_survives_other_partial_plate_lines(self):
        field = extracted('serial', 'FORK123456', evidence='SERIAL No. FORK123456')
        for transcription in (
                'MODEL: [ilegible]\nSERIAL No. FORK123456\nTIRE PRESSURE XXX/XXX psi',
                'MODEL FORK20 SERIAL No. FORK123456 EXAMPLE CO. FRONT TIRE SIZE 20X8X16',
                'Modelo FORK20\nNúmero de serie: FORK123456\nPresión: [ilegible]',
                'S/N: FORK123456\nTIRE PRESSURE XXX/XXX psi'):
            with self.subTest(transcription=transcription):
                result = normalize_analysis(analysis([field], transcription, readability='partial'), [ASSET])
                self.assertEqual(result['data']['serial'], 'FORK123456')
                self.assertEqual(result['provenance']['serial']['review'], 'clear')
                self.assertEqual(result['plates'][0]['readability'], 'partial')
                self.assertNotIn('FORK123456', result['data']['description'])

    def test_never_reconstructs_null_or_uncertain_serial_from_complete_transcription(self):
        for value, review in ((None, 'needs_review'), ('FORK123456', 'needs_review'),
                              (None, 'clear'), ('FORK12345?', 'clear')):
            with self.subTest(value=value, review=review):
                result = normalize_analysis(analysis([extracted('serial', value, review=review,
                    evidence='SERIAL No. FORK123456')], 'SERIAL No. FORK123456', readability='partial'), [ASSET])
                self.assertIsNone(result['data']['serial'])
                self.assertEqual(result['provenance']['serial']['review'], 'needs_review')

    def test_ambiguous_conflicting_or_longer_serial_line_is_rejected(self):
        field = extracted('serial', 'FORK123456')
        for transcription in (
                'SERIAL No. [ilegible]FORK123456', 'SERIAL No. FORK123456?',
                'SERIAL No. FORK123456 [ilegible]', 'SERIAL No. FORK1234567',
                'SERIAL No. XFORK123456', 'SERIAL No. FORK123456-7',
                'SERIAL No. FORK123456 or FORK123458',
                'SERIAL No. FORK123456 / FORK123458', 'SERIAL No. FORK123456...',
                'SERIAL No. FORK123456\nSERIAL No. OTHER67890',
                'PART No. FORK123456', 'ENGINE SERIAL No. FORK123456',
                'Model FORK123456; no serial visible'):
            with self.subTest(transcription=transcription):
                result = normalize_analysis(analysis([field], transcription, readability='partial'), [ASSET])
                self.assertIsNone(result['data']['serial'])

    def test_serial_helper_requires_machine_component_bound_asset_and_clear_reading(self):
        field = extracted('serial', 'FORK123456')
        plate = {'asset_id': ASSET, 'component': 'machine', 'readability': 'partial',
                 'transcription': 'SERIAL No. FORK123456'}
        self.assertTrue(plate_serial_is_clear(field, plate))
        for changed in ({'source': 'image'}, {'component': 'engine'}, {'asset_id': 'foreign'},
                        {'review': 'not_identifiable'}, {'key': 'model'}):
            with self.subTest(changed=changed):
                self.assertFalse(plate_serial_is_clear({**field, **changed}, plate))
        self.assertFalse(plate_serial_is_clear(field, {**plate, 'readability': 'unreadable'}))
        self.assertFalse(plate_serial_is_clear(field, {**plate, 'component': 'engine'}))
        self.assertFalse(plate_serial_is_clear(field, None))

    def test_legacy_fully_clear_plate_still_requires_a_complete_literal_serial(self):
        field = extracted('serial', 'FORK123456')
        plate = {'asset_id': ASSET, 'component': 'machine', 'readability': 'clear',
                 'transcription': 'FORK123456'}
        self.assertTrue(plate_serial_is_clear(field, plate))
        self.assertFalse(plate_serial_is_clear(field, {**plate, 'readability': 'partial'}))
        self.assertFalse(plate_serial_is_clear(field, {**plate, 'transcription': 'FORK1234567'}))
