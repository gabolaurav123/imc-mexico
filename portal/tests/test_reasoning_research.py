"""Luna keeps bounded calls, charges unknown outcomes, and never falls back."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from portal.research import (UsageTotals,
    research_machine, research_reservation, is_validated_web_field, merge_research)
from portal.research_pipeline import ResearchBudgetExhausted, _normalize
from portal.valuation import estimate_machine, valuation_reservation, is_validated_estimate
from portal.tests.test_research import candidate, vision, web_response, IDENTITY, URL, TEXT
from portal.tests.test_research_stages import response, extraction
from portal.tests.test_valuation import provider, html, quote, URLS, vision as valuation_vision


LUNA = 'gpt-5.6-luna'


class ReasoningResearchTests(SimpleTestCase):
    def test_staged_discovery_and_final_extraction_use_same_astra_low_without_extra_calls(self):
        client = Mock()
        result = vision(serial='UNIT123')
        result['data'].pop('model')
        result['provenance'].pop('model')
        client.responses.create.side_effect = [response('Caterpillar modelo 420F2, número de serie UNIT123.'),
            response(TEXT), web_response(sources=[])]
        model = candidate(key='model', value='420F2', scope='exact_serial', matched_serial='UNIT123')
        client.responses.parse.side_effect = [extraction(model), extraction(model, candidate(1))]
        with patch('portal.research_documents.collect_document_fields', return_value=([], [], False)):
            value, _ = research_machine(client, LUNA, result)
        self.assertEqual({field['key'] for field in value['fields']}, {'model', 'power'})
        self.assertEqual(client.responses.create.call_count, 3)
        self.assertEqual(client.responses.parse.call_count, 2)
        for method, expected_output in ((client.responses.create, 6500), (client.responses.parse, 7500)):
            for call in method.call_args_list:
                self.assertEqual(call.kwargs['model'], LUNA)
                self.assertEqual(call.kwargs['reasoning'], {'effort': 'low'})
                self.assertEqual(call.kwargs['max_output_tokens'], expected_output)
                self.assertEqual(call.kwargs['timeout'], 120)
                self.assertFalse(call.kwargs['store'])
        for call in client.responses.create.call_args_list:
            self.assertEqual(call.kwargs['max_tool_calls'], 1)
            self.assertEqual(call.kwargs['tool_choice'], 'required')

    def test_model_aware_reservations_keep_legacy_and_add_each_reasoning_request(self):
        self.assertEqual(research_reservation('gpt-4.1-mini'), 78000)
        self.assertEqual(research_reservation(LUNA), 95500)
        self.assertEqual(valuation_reservation('gpt-4.1-mini'), 36000)
        self.assertEqual(valuation_reservation(LUNA), 43000)

    def test_missing_usage_charges_full_allocations_in_search_and_normalization(self):
        for model, search_allocation, parse_allocation in (('gpt-4.1-mini', 14000, 18000), (LUNA, 17500, 21500)):
            with self.subTest(model=model):
                client = Mock()
                search = response(TEXT)
                search.usage = None
                parsed = extraction(candidate())
                parsed.usage = None
                client.responses.create.return_value = search
                client.responses.parse.return_value = parsed
                with patch('portal.research_documents.collect_document_fields', return_value=([], [], False)):
                    result, usage = research_machine(client, model, vision())
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(usage.estimated_tokens, 3 * search_allocation + parse_allocation)
                self.assertEqual(usage.input_tokens, usage.estimated_tokens)
                self.assertEqual(usage.output_tokens, 0)
                self.assertEqual(usage.web_search_calls, 3)

    def test_search_admission_stops_before_outbound_request_one_token_over_remaining_allocation(self):
        client = Mock()
        # First response spends 78001 including the conservative web allowance;
        # the next 17500 cannot fit in the reserved 95500.
        client.responses.create.return_value = web_response(sources=[], input_tokens=70001, output_tokens=0)
        value, usage = research_machine(client, LUNA, vision())
        self.assertEqual(client.responses.create.call_count, 1)
        client.responses.parse.assert_not_called()
        self.assertEqual(usage.input_tokens, 78001)
        self.assertEqual(value['status'], 'degraded')
        self.assertEqual(value['diagnostics']['stages'][-1]['status'], 'budget_unavailable')

    def test_normalizer_admission_at_boundary_and_over_does_not_charge_unstarted_call(self):
        passages = [{'passage_index': 0, 'source_url': URL, 'source_title': 'Caterpillar 420F2', 'text': TEXT}]
        for extra in (0, 1):
            with self.subTest(extra=extra):
                client = Mock()
                client.responses.parse.return_value = extraction(candidate())
                usage = UsageTotals(input_tokens=74000 + extra)
                if extra:
                    with self.assertRaises(ResearchBudgetExhausted):
                        _normalize(client, LUNA, IDENTITY, 'model', [{'url': URL, 'title': 'Caterpillar 420F2'}],
                                   passages, {}, usage)
                    client.responses.parse.assert_not_called()
                    self.assertEqual(usage.input_tokens, 74001)
                    self.assertEqual(usage.estimated_tokens, 0)
                else:
                    value = _normalize(client, LUNA, IDENTITY, 'model', [{'url': URL, 'title': 'Caterpillar 420F2'}],
                                       passages, {}, usage)
                    self.assertEqual(value['fields'][0]['value'], '70 kW')
                    self.assertEqual(usage.output_tokens, 100)

    def test_exhausted_normalization_preserves_signed_direct_evidence_without_another_call(self):
        from portal.tests.test_research import fact
        client = Mock()
        client.responses.create.side_effect = [web_response(sources=[], input_tokens=70001, output_tokens=0)]

        def documents(identity, retrieved, sources, passages, titles, allowed):
            sources.append({'url': URL, 'title': 'Caterpillar 420F2'})
            passages.append({'passage_index': 0, 'source_url': URL, 'source_title': 'Caterpillar 420F2',
                             'text': TEXT, 'origin': 'direct_document'})
            return [fact()], [], False

        # Retain a retrieved URL, but no model passage. Direct rows can still be
        # normalized locally after further paid phases lose admission.
        first = web_response(sources=[{'url': URL}], input_tokens=70001, output_tokens=0, text='No specification.')
        client.responses.create.side_effect = [first]
        with patch('portal.research_documents.collect_document_fields', side_effect=documents):
            value, _ = research_machine(client, LUNA, vision())
        client.responses.parse.assert_not_called()
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(value['fields'][0]['value'], '70 kW')
        result = merge_research({'data': {}, 'provenance': {}, 'fields': [], 'warnings': []}, value)
        self.assertTrue(is_validated_web_field(result, 'power', '70 kW', result['provenance']['power']))

    def test_category_request_is_astra_bounded_and_missing_usage_or_timeout_is_charged(self):
        for failure in ('missing_usage', 'timeout'):
            with self.subTest(failure=failure):
                client = Mock()
                search = web_response(sources=[])
                search.usage = None
                client.responses.create.return_value = search
                if failure == 'timeout':
                    client.responses.create.side_effect = TimeoutError('private')
                value, usage = research_machine(client, LUNA,
                    {'data': {}, 'provenance': {}, 'category': 'Motoniveladoras'},
                    allowed_categories=['Motoniveladoras'])
                request = client.responses.create.call_args.kwargs
                self.assertEqual(request['max_output_tokens'], 5300)
                self.assertEqual(request['timeout'], 120)
                self.assertEqual(request['reasoning'], {'effort': 'low'})
                self.assertEqual(usage.estimated_tokens, 17500)
                self.assertNotIn('private', str(value))
                client.responses.parse.assert_not_called()

    def test_reasoning_output_is_counted_once_without_saving_reasoning_text(self):
        client = Mock()
        search = web_response(sources=[], input_tokens=120, output_tokens=500)
        search.usage.output_tokens_details = SimpleNamespace(reasoning_tokens=400)
        client.responses.create.return_value = search
        _, usage = research_machine(client, LUNA, vision())
        self.assertEqual(usage.output_tokens, 1500)
        self.assertEqual(usage.input_tokens, 3 * 8120)


class ReasoningValuationTests(SimpleTestCase):
    def run_estimate(self, client, model=LUNA):
        with patch('portal.valuation._fetch_listing', side_effect=[(html(), URLS[0]), (html(quote('USD 16,000')), URLS[1])]):
            return estimate_machine(client, model, valuation_vision(), {})

    def test_astra_direct_listings_remain_grounded_with_same_two_calls(self):
        client = provider()
        value, _ = self.run_estimate(client)
        self.assertEqual(value['status'], 'estimated')
        self.assertTrue(is_validated_estimate(value))
        for method, output in ((client.responses.create, 6500), (client.responses.parse, 6000)):
            self.assertEqual(method.call_count, 1)
            self.assertEqual(method.call_args.kwargs['model'], LUNA)
            self.assertEqual(method.call_args.kwargs['reasoning'], {'effort': 'low'})
            self.assertEqual(method.call_args.kwargs['max_output_tokens'], output)
            self.assertEqual(method.call_args.kwargs['timeout'], 120)

    def test_parse_admission_includes_astra_allocation_at_exact_boundary_and_one_over(self):
        for extra in (0, 1):
            with self.subTest(extra=extra):
                client = provider()
                client.responses.create.return_value.usage.input_tokens = 30500 - 8000 - 100 + extra
                value, usage = self.run_estimate(client)
                self.assertEqual(client.responses.parse.call_count, 0 if extra else 1)
                if extra:
                    self.assertEqual(value['diagnostics']['stop_reason'], 'parse_reservation_unavailable')
                    self.assertEqual(usage.input_tokens + usage.output_tokens, 30501)
                else:
                    self.assertEqual(value['status'], 'estimated')

    def test_each_missing_usage_phase_is_fully_charged_without_double_web_estimate(self):
        client = provider(search_usage=False)
        client.responses.parse.return_value.usage = None
        value, usage = self.run_estimate(client)
        self.assertEqual(value['status'], 'estimated')
        self.assertEqual(usage.estimated_tokens, 43000)
        self.assertEqual(usage.input_tokens, 43000)
        self.assertEqual(usage.output_tokens, 0)
        self.assertEqual(usage.web_search_calls, 1)

    def test_parse_timeout_keeps_measured_search_and_charges_reasoning_allocation(self):
        client = provider()
        client.responses.parse.side_effect = TimeoutError('private')
        value, usage = self.run_estimate(client)
        self.assertEqual(value['status'], 'insufficient')
        self.assertEqual(usage.estimated_tokens, 8000 + 12500)
        self.assertEqual(usage.input_tokens, 8200 + 12500)
        self.assertEqual(usage.output_tokens, 100)
        self.assertNotIn('private', str(value))

    def test_legacy_request_limits_and_options_are_unchanged(self):
        client = provider()
        self.run_estimate(client, 'gpt-4.1-mini')
        for method, timeout, output in ((client.responses.create, 60, 3000), (client.responses.parse, 45, 2500)):
            request = method.call_args.kwargs
            self.assertEqual(request['timeout'], timeout)
            self.assertEqual(request['max_output_tokens'], output)
            self.assertNotIn('reasoning', request)
