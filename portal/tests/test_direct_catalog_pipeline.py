from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from portal.research import _direct_catalog_context, is_validated_general_context, research_machine


IDENTITY = {'brand': 'DEVELON', 'category': 'Excavadoras', 'model': None, 'serial': None}
URL = 'https://eu.develon-ce.com/en/products/crawler-excavators'
TITLE = 'Crawler Excavators | Develon Europe'
LEAD = {'model': 'DX225LC-7 SLR', 'status': 'hypothesis', 'confidence': 'lead',
        'support_count': 1, 'source_url': URL, 'source_title': TITLE,
        'source_date': '2026-09-18', 'evidence': 'DX225LC-7 SLR',
        'supporting_sources': [{'url': URL, 'title': TITLE}]}


class DirectCatalogPipelineTests(SimpleTestCase):
    def test_direct_document_reference_is_signed_without_any_paid_model_call(self):
        client = Mock()
        result = {'data': {'brand': 'DEVELON'}, 'category': 'Excavadoras',
                  'provenance': {'brand': {'source': 'image', 'review': 'clear', 'component': 'machine'}}}
        with patch('portal.research_catalog.catalog_listing_candidates', return_value=[LEAD]):
            research, usage = research_machine(client, 'gpt-5.6-luna', result,
                                               allowed_categories=['Excavadoras'])
        self.assertTrue(is_validated_general_context({'research': research}))
        self.assertEqual(research['hypotheses'][0]['model'], 'DX225LC-7 SLR')
        self.assertEqual(research['fields'], [])
        self.assertIsNone(research['identity']['model'])
        self.assertEqual(usage.input_tokens + usage.output_tokens + usage.web_search_calls, 0)
        client.responses.create.assert_not_called()
        client.responses.parse.assert_not_called()

    def test_withdrawal_after_fetch_discards_leads(self):
        with patch('portal.research_catalog.catalog_listing_candidates', return_value=[LEAD]):
            result = _direct_catalog_context(IDENTITY, Mock(side_effect=[True, False]))
        self.assertEqual(result['status'], 'degraded')
        self.assertEqual(result['hypotheses'], [])
        self.assertEqual(result['sources'], [])

    def test_unavailable_catalog_falls_through_and_tampered_lead_is_rejected(self):
        for leads in ([], [{**LEAD, 'model': 'DX999'}]):
            with self.subTest(leads=leads), patch('portal.research_catalog.catalog_listing_candidates', return_value=leads):
                self.assertIsNone(_direct_catalog_context(IDENTITY))
