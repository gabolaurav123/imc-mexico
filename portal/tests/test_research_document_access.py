"""Search snippets from unread documents do not become technical facts."""
from django.test import SimpleTestCase

from portal.research import ResearchExtraction, ResearchField, normalize_research


IDENTITY = {'brand': 'Caterpillar', 'model': '2EC25', 'serial': 'TEST0123'}


def normalize(url, scope='model', key='load_center', value='500 mm (20 pulgadas)', direct=False):
    exact = scope == 'exact_serial'
    text = 'Caterpillar 2EC25' + (', S/N: TEST0123' if exact else '') + f'. {key}: {value}.'
    field = ResearchField(key=key, value=value, scope=scope, source_url=url, evidence=text,
        matched_brand='Caterpillar', matched_model='2EC25', matched_serial='TEST0123' if exact else None)
    return normalize_research(ResearchExtraction(fields=[] if direct else [field]), IDENTITY,
        'exact_serial' if exact else 'model', [{'url': url, 'title': 'Caterpillar 2EC25 specifications'}],
        text, citations={url: [text]}, direct_fields=[field] if direct else ())


class ResearchDocumentAccessTests(SimpleTestCase):
    def test_scribd_summaries_cannot_prove_model_or_exact_unit_fields(self):
        for host in ('scribd.com', 'www.scribd.com', 'es.scribd.com'):
            for scope in ('model', 'exact_serial'):
                for key, value in (('load_center', '500 mm (20 pulgadas)'), ('capacity', '2500 kg'),
                                   ('weight', '10640 lb'), ('power', '70 kW'), ('voltage', '36 V')):
                    with self.subTest(host=host, scope=scope, key=key):
                        result = normalize(f'https://{host}/document/123/test?utm_source=openai', scope, key, value)
                        self.assertEqual(result['fields'], [])
                        self.assertEqual(result['diagnostics']['rejection_counts'], {'readable_document_required': 1})
                        self.assertEqual(result['diagnostics']['field_rejection_counts'][key], {'readable_document_required': 1})

    def test_direct_candidate_flag_does_not_claim_an_unavailable_reader(self):
        result = normalize('https://www.scribd.com/document/123/test', 'exact_serial', direct=True)
        self.assertEqual(result['fields'], [])
        self.assertEqual(result['diagnostics']['rejection_counts'], {'readable_document_required': 1})

    def test_other_origins_and_smith_exact_fields_keep_existing_rules(self):
        for url, scope, direct in (
            ('https://www.smithmachinery.com/listing/test-forklift/', 'exact_serial', True),
            ('https://example.com/manual', 'model', False),
            ('https://notscribd.com/manual', 'model', False),
        ):
            with self.subTest(url=url):
                result = normalize(url, scope, key='voltage', value='36 V', direct=direct)
                self.assertEqual([field['value'] for field in result['fields']], ['36 V'])
                self.assertEqual(result['diagnostics']['rejection_counts'], {})
