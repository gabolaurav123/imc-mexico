"""Reasoning tool output items are not all successfully executed searches."""
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from portal.research import (response_sources, web_search_completed, web_search_diagnostics,
    research_machine, merge_research, is_validated_web_field)
from portal.valuation import estimate_machine
from portal.tests.test_research import web_response, vision, candidate, URL, TEXT
from portal.tests.test_research_stages import extraction
from portal.tests.test_valuation import provider, html, quote, URLS, vision as valuation_vision


OTHER = 'https://invalid-reading.example.org/other-machine'


def tool(status='completed', action='search', url=URL):
    return {'type': 'web_search_call', 'status': status,
            'action': {'type': action, 'sources': [{'url': url, 'title': 'Caterpillar 420F2'}]}}


def searched(extra=(), input_tokens=120, output_tokens=80):
    value = web_response(input_tokens=input_tokens, output_tokens=output_tokens)
    value.output[0] = tool()
    value.output[1:1] = list(extra)
    return value


class WebSearchStatusTests(SimpleTestCase):
    def test_only_completed_search_can_authorize_source_but_every_item_counts(self):
        invalid = [tool(status=status, url=OTHER) for status in ('failed', 'incomplete', 'searching', 'in_progress', None)]
        invalid += [tool(action=action, url=OTHER) for action in ('open_page', 'find_in_page', None)]
        response = searched(invalid)
        diagnostics = {}
        sources, calls = response_sources(response, diagnostics)
        self.assertEqual([source['url'] for source in sources], [URL])
        self.assertEqual(calls, 9)
        self.assertEqual(diagnostics['reported_web_calls'], 9)
        self.assertEqual(diagnostics['completed_search_calls'], 1)
        self.assertEqual(diagnostics['web_call_action_counts']['open_page'], 1)
        self.assertEqual(diagnostics['web_call_status_counts']['failed'], 1)
        self.assertTrue(web_search_completed(response))

    def test_failed_only_missing_contract_and_page_actions_cannot_claim_success(self):
        for item in (tool(status='failed'), tool(status=None), tool(action=None),
                     tool(action='open_page'), tool(action='find_in_page')):
            with self.subTest(item=item):
                response = searched()
                response.output[0] = item
                sources, calls = response_sources(response)
                self.assertEqual(sources, [])
                self.assertEqual(calls, 1)
                self.assertFalse(web_search_completed(response))

    def test_response_must_finish_and_diagnostics_cannot_leak_arbitrary_provider_text(self):
        response = searched([tool(status='private serial OWNER123', action='query person@example.com')])
        response.status = 'incomplete'
        response.incomplete_details = {'reason': 'max_output_tokens'}
        metrics = web_search_diagnostics(response)
        self.assertFalse(web_search_completed(response))
        self.assertEqual(metrics['incomplete_reason'], 'max_output_tokens')
        self.assertEqual(metrics['web_call_status_counts']['unknown'], 1)
        self.assertNotIn('OWNER123', str(metrics))
        self.assertNotIn('example.com', str(metrics))
        response.incomplete_details['reason'] = 'private token'
        self.assertEqual(web_search_diagnostics(response)['incomplete_reason'], 'unknown')

    def test_two_completed_searches_are_counted_without_discarding_retrieved_evidence(self):
        response = searched([tool(url='https://www.cat.com/second-public-source')])
        sources, calls = response_sources(response)
        self.assertEqual(calls, 2)
        self.assertEqual(len(sources), 2)
        self.assertTrue(web_search_completed(response))

    def test_annotations_cannot_resurrect_failed_only_source(self):
        response = searched([tool(status='failed', url=OTHER)])
        annotation = response.output[-1]['content'][0]['annotations'][0]
        annotation['url'] = OTHER
        response.output_text = response.output_text.replace(URL, OTHER)
        response.output[-1]['content'][0]['text'] = response.output_text
        sources, _ = response_sources(response)
        self.assertNotIn(OTHER, {source['url'] for source in sources})

    def test_valid_search_plus_unsuccessful_attempt_survives_all_research_stages(self):
        client = Mock()
        client.responses.create.return_value = searched([tool(status='failed', url=OTHER)])
        client.responses.parse.return_value = extraction(candidate())
        with patch('portal.research_documents.collect_document_fields', return_value=([], [], False)):
            value, usage = research_machine(client, 'gpt-5.6-luna', vision())
        self.assertEqual(value['status'], 'completed')
        self.assertEqual(value['fields'][0]['value'], '70 kW')
        self.assertEqual(client.responses.create.call_count, 3)
        self.assertEqual(client.responses.parse.call_count, 1)
        self.assertEqual(usage.web_search_calls, 6)
        self.assertEqual(usage.estimated_tokens, 48000)
        self.assertTrue(value['diagnostics']['search_complete'])
        for stage in value['diagnostics']['stages']:
            self.assertEqual(stage['completed_search_calls'], 1)
            self.assertEqual(stage['web_call_status_counts'], {'completed': 1, 'failed': 1})
            self.assertEqual(stage['response_status'], 'completed')
        for request in client.responses.create.call_args_list:
            self.assertEqual(request.kwargs['max_tool_calls'], 1)
        self.assertNotIn(OTHER, {source['url'] for source in value['sources']})

    def test_optional_search_stops_to_preserve_final_extraction_headroom(self):
        client = Mock()
        # Each response has measured 14000 plus 16000 conservative allowance.
        # Two searches cost60000; a third allocation17500 + extraction21500
        # would exceed95500. The already collected evidence remains useful.
        client.responses.create.return_value = searched([tool(status='failed', url=OTHER)], input_tokens=13900, output_tokens=100)
        client.responses.parse.return_value = extraction(candidate())
        with patch('portal.research_documents.collect_document_fields', return_value=([], [], False)):
            value, usage = research_machine(client, 'gpt-5.6-luna', vision())
        self.assertEqual(client.responses.create.call_count, 2)
        self.assertEqual(client.responses.parse.call_count, 1)
        self.assertEqual(value['status'], 'completed')
        self.assertFalse(value['diagnostics']['search_complete'])
        self.assertEqual(value['diagnostics']['stages'][-1]['status'], 'budget_unavailable')
        self.assertEqual(usage.input_tokens + usage.output_tokens, 60300)
        self.assertEqual(usage.web_search_calls, 4)
        result = merge_research({'data': {}, 'provenance': {}, 'fields': [], 'warnings': []}, value)
        self.assertTrue(is_validated_web_field(result, 'power', '70 kW', result['provenance']['power']))

    def test_observed_search_cost_is_floor_for_optional_next_search(self):
        client = Mock()
        # 42000 is materially above the configured17500 search allocation.
        # Another observed-size call plus final21500 would total105500.
        client.responses.create.return_value = searched([tool(status='failed', url=OTHER)], input_tokens=25900, output_tokens=100)
        client.responses.parse.return_value = extraction(candidate())
        with patch('portal.research_documents.collect_document_fields', return_value=([], [], False)):
            value, usage = research_machine(client, 'gpt-5.6-luna', vision())
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(client.responses.parse.call_count, 1)
        self.assertEqual(value['status'], 'completed')
        self.assertEqual(usage.input_tokens + usage.output_tokens, 42300)
        self.assertEqual(value['diagnostics']['stages'][-1]['status'], 'budget_unavailable')

    def test_missing_usage_charges_full_allocation_plus_each_additional_reported_item(self):
        response = searched([tool(status='failed', url=OTHER)])
        response.usage = None
        client = Mock()
        client.responses.create.return_value = response
        client.responses.parse.return_value = extraction(candidate())
        with patch('portal.research_documents.collect_document_fields', return_value=([], [], False)):
            value, usage = research_machine(client, 'gpt-5.6-luna', vision())
        self.assertEqual(value['status'], 'completed')
        self.assertEqual(client.responses.create.call_count, 2)
        self.assertEqual(usage.estimated_tokens, 2 * (17500 + 8000))
        self.assertEqual(usage.web_search_calls, 4)

        category = vision()
        category['data'].pop('model')
        category['provenance'].pop('model')
        value, usage = research_machine(client, 'gpt-5.6-luna', category, allowed_categories=['Retroexcavadoras'])
        self.assertEqual(value['status'], 'general_context')
        self.assertEqual(usage.estimated_tokens, 17500 + 8000)

        valuation = provider(search_usage=False)
        valuation.responses.create.return_value.output[0].update(status='completed')
        valuation.responses.create.return_value.output[0]['action']['type'] = 'search'
        valuation.responses.create.return_value.output.append(tool(status='failed', url=OTHER))
        with patch('portal.valuation._fetch_listing', side_effect=[(html(), URLS[0]), (html(quote('USD 16,000')), URLS[1])]):
            value, usage = estimate_machine(valuation, 'gpt-5.6-luna', valuation_vision(), {})
        self.assertEqual(usage.estimated_tokens, 30500 + 8000)
        self.assertEqual(usage.web_search_calls, 2)
        valuation.responses.parse.assert_not_called()
        self.assertEqual(value['diagnostics']['stop_reason'], 'parse_reservation_unavailable')

    def test_category_accepts_completed_search_with_extra_failure_and_keeps_accounting(self):
        client = Mock()
        client.responses.create.return_value = searched([tool(status='failed', url=OTHER)])
        result = vision()
        result['data'].pop('model')
        result['provenance'].pop('model')
        value, usage = research_machine(client, 'gpt-5.6-luna', result, allowed_categories=['Retroexcavadoras'])
        self.assertEqual(value['status'], 'general_context')
        self.assertEqual(value['fields'], [])
        self.assertEqual(usage.web_search_calls, 2)
        self.assertEqual(usage.estimated_tokens, 16000)
        self.assertEqual(value['diagnostics']['completed_search_calls'], 1)

    def test_valuation_reads_only_successful_search_inventory_and_logs_safe_counts(self):
        client = provider()
        search = client.responses.create.return_value
        search.output[0].update(status='completed')
        search.output[0]['action']['type'] = 'search'
        search.output.append(tool(status='failed', url=OTHER))
        with patch('portal.valuation._fetch_listing', side_effect=[(html(), URLS[0]), (html(quote('USD 16,000')), URLS[1])]) as fetch:
            value, usage = estimate_machine(client, 'gpt-5.6-luna', valuation_vision(), {})
        self.assertEqual(value['status'], 'estimated')
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(usage.web_search_calls, 2)
        self.assertEqual(usage.estimated_tokens, 16000)
        self.assertEqual(value['diagnostics']['phases'][0]['completed_search_calls'], 1)
        self.assertEqual(value['diagnostics']['phases'][0]['web_call_status_counts'], {'completed': 1, 'failed': 1})
        self.assertEqual(client.responses.create.call_args.kwargs['max_tool_calls'], 2)

    def test_no_completed_search_never_buys_normalization_or_fetches_listings(self):
        client = provider()
        client.responses.create.return_value.output[0].update(status='failed')
        client.responses.create.return_value.output[0]['action']['type'] = 'search'
        with patch('portal.valuation._fetch_listing') as fetch:
            value, usage = estimate_machine(client, 'gpt-5.6-luna', valuation_vision(), {})
        self.assertEqual(value['status'], 'insufficient')
        fetch.assert_not_called()
        client.responses.parse.assert_not_called()
        self.assertEqual(usage.web_search_calls, 1)
        self.assertEqual(usage.estimated_tokens, 8000)
