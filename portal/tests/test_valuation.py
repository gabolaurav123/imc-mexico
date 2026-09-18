"""Price references require actual readable listings, not generated citations."""
import copy
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from portal.valuation import (ComparableCandidate, ComparableCandidates, Configuration,
    LABEL, PARSE_RESERVATION, SEARCH_RESERVATION, VALUATION_RESERVATION,
    _document_passages, _fetch_listing, _identity, _listing_url, _listing_fact_snippets, _money, _normalize,
    estimate_machine, is_validated_estimate)
from portal.research_fetch import CatalogFetchError


IDENTITY = {'brand': 'Caterpillar', 'model': '2EC25', 'condition': 'used', 'configurations': {}}
URLS = ['https://dealer-one.example.com/equipment/unit-a', 'https://dealer-two.example.org/equipment/unit-b']


def quote(price='USD 12,000', **options):
    return ('Caterpillar 2EC25. ' + options.get('label', 'Asking price') + ': ' + price + '. '
            + 'Location: ' + options.get('country', 'United States') + '. '
            + 'Condition: ' + options.get('condition', 'Used') + '. ' + options.get('extra', '')).strip()


def passage(text=None, index=0, **changes):
    value = dict(url=URLS[index % 2], title='Caterpillar 2EC25 for sale', heading='Caterpillar 2EC25',
                 text=text or quote(), _origin='direct_html', _unit_hash='')
    value.update(changes)
    return value


def candidate(index=0, text=None, price='USD 12,000', **changes):
    values = dict(passage_index=index, evidence=text or quote(price), price_literal=price,
                  currency='USD', market='US', price_type='asking', condition='used')
    values.update(changes)
    return ComparableCandidate(**values)


def normalize(candidates=None, passages=None, identity=None):
    return _normalize(ComparableCandidates(fields=candidates if candidates is not None else [candidate()]),
                      passages or [passage()], identity or copy.deepcopy(IDENTITY))


def vision():
    data = {'brand': 'Caterpillar', 'model': '2EC25', 'usage_condition': 'Usada'}
    return {'data': data, 'provenance': {
        'brand': {'source': 'image', 'review': 'clear', 'component': 'machine'},
        'model': {'source': 'plate', 'review': 'clear', 'component': 'machine'},
        'usage_condition': {'source': 'visual_proposal', 'review': 'needs_review', 'component': 'machine'}}}


def html(text=None, heading='Caterpillar 2EC25', extras=''):
    return f'<html><head><title>{heading} for sale</title></head><body><nav>New &amp; Used USD 1</nav><main><h1>{heading}</h1><p>{text or quote()}</p>{extras}</main></body></html>'


def provider(urls=None, parsed=None, search_usage=True):
    urls = urls or URLS
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(status='completed', output_text='An invented asking price USD 1.',
        usage=SimpleNamespace(input_tokens=200, output_tokens=100) if search_usage else None,
        output=[{'type': 'web_search_call', 'status': 'completed', 'action': {'type': 'search', 'sources': [{'url': url, 'title': 'Caterpillar 2EC25'} for url in urls]}}])
    client.responses.parse.return_value = SimpleNamespace(status='completed',
        usage=SimpleNamespace(input_tokens=700, output_tokens=200),
        output_parsed=parsed or ComparableCandidates(fields=[candidate(), candidate(1, price='USD 16,000')]))
    return client


class ValuationGroundingTests(SimpleTestCase):
    def test_two_literal_independent_used_asking_listings_produce_signed_range_and_median(self):
        value = normalize([candidate(), candidate(1, price='USD 16,000')],
                          [passage(), passage(quote('USD 16,000'), 1)])
        self.assertEqual(value['status'], 'estimated')
        self.assertEqual(value['suggested_price'], '14000.00')
        self.assertEqual(value['fields']['estimate_min'], '12000.00')
        self.assertEqual(value['fields']['estimate_max'], '16000.00')
        self.assertEqual(value['fields']['estimate_currency'], 'USD')
        self.assertEqual(value['fields']['estimate_market'], 'Estados Unidos')
        self.assertIn(LABEL, value['fields']['estimate_basis'])
        self.assertIn('no acreditan una venta', value['fields']['estimate_basis'])
        self.assertTrue(is_validated_estimate(value))

    def test_a_single_comparable_is_insufficient_and_gap_is_signed(self):
        value = normalize()
        self.assertEqual(value['status'], 'insufficient')
        self.assertIsNone(value['suggested_price'])
        self.assertIn('segunda unidad', value['fields']['estimate_missing_info'])
        self.assertTrue(is_validated_estimate(value))
        value['fields']['estimate_missing_info'] = 'No falta nada'
        self.assertFalse(is_validated_estimate(value))

    def test_price_cannot_be_rewritten_or_borrowed_from_another_page(self):
        for item in [candidate(price='USD 20,000'), candidate(price='USD 12,000', currency='MXN'),
                     candidate(text=quote().replace('12,000', '13,000')), candidate(index=3)]:
            with self.subTest(item=item):
                result = normalize([item])
                self.assertFalse(result['comparables'])
                self.assertEqual(result['status'], 'insufficient')
        value = normalize([candidate()], [passage(_origin='web_summary')])
        self.assertFalse(value['comparables'])
        # A prefix of a larger printed price is not that price.
        text = quote('USD 12,000,000')
        self.assertFalse(normalize([candidate(text=text)], [passage(text)])['comparables'])
        text = quote().replace('2EC25', '2EC30')
        self.assertFalse(normalize([candidate(text=text)], [passage(text)])['comparables'])

    def test_bare_dollar_currency_is_never_inferred_from_country(self):
        text = quote('$12,000')
        value = normalize([candidate(text=text, price='$12,000')], [passage(text)])
        self.assertFalse(value['comparables'])
        for literal, currency, expected in [('USD 12,000.50', 'USD', '12000.50'),
                ('12.000,50 EUR', 'EUR', '12000.50'), ('MXN 240000', 'MXN', '240000'),
                ('US$ 12,000', 'USD', '12000'), ('$12,000', 'USD', None),
                ('CAD 12,000', 'USD', None), ('USD 12.000,500', 'USD', None)]:
            with self.subTest(literal=literal):
                amount = _money(literal, currency)
                self.assertEqual(str(amount) if amount is not None else None, expected)

    def test_sold_badge_does_not_transform_asking_price_or_active_bid(self):
        cases = [(quote(extra='SOLD'), 'sold'), (quote(label='Current bid'), 'sold'),
                 (quote(label='Winning bid'), 'sold'), (quote(label='Sold for', extra='Not sold'), 'sold')]
        for text, kind in cases:
            with self.subTest(text=text):
                self.assertFalse(normalize([candidate(text=text, price_type=kind)], [passage(text)])['comparables'])
        text = quote(label='Sold for')
        result = normalize([candidate(text=text, price_type='sold')], [passage(text)])
        self.assertEqual(result['comparables'][0]['price_type'], 'sold')

    def test_listing_price_and_price_in_exact_for_sale_heading_are_asking(self):
        for label, heading in [('Listing price', 'Caterpillar 2EC25'),
                               ('Price', 'Used Caterpillar 2EC25 for sale')]:
            text = quote(label=label)
            with self.subTest(label=label):
                value = normalize([candidate(text=text)], [passage(text, heading=heading)])
                self.assertEqual(value['comparables'][0]['price_type'], 'asking')
                self.assertEqual(value['comparables'][0]['price'], '12000.00')

    def test_heading_sale_context_cannot_certify_final_sale_or_replace_price_label(self):
        for label, heading, kind in [
                ('Price', 'Caterpillar 2EC25 SoldOut', 'sold'),
                ('Listing price', 'Caterpillar 2EC25 SoldOut', 'sold'),
                ('Current bid', 'Caterpillar 2EC25 for sale', 'asking'),
                ('Deposit', 'Caterpillar 2EC25 for sale', 'asking'),
                ('Monthly', 'Caterpillar 2EC25 for sale', 'asking'),
                ('Price', 'Caterpillar 2EC25 IT for sale', 'asking'),
                ('Price', 'Caterpillar 2EC25 rental for sale', 'asking'),
                ('Listing price', 'Caterpillar 2EC25 rental', 'asking'),
        ]:
            text = quote(label=label)
            with self.subTest(label=label, heading=heading):
                value = normalize([candidate(text=text, price_type=kind)], [passage(text, heading=heading)])
                self.assertFalse(value['comparables'])

    def test_rejected_candidate_diagnostics_have_safe_pointers_not_quotes_contacts_or_serials(self):
        text = quote(label='Price', extra='Serial number: PRIVATE12345. Contact owner@example.com +1 800 555 1212.')
        title = 'Caterpillar 2EC25 PRIVATE12345 owner@example.com +1 800 555 1212'
        value = normalize([candidate(text=text)], [passage(text, title=title,
                          url='https://dealer.example.com/equipment/PRIVATE12345?phone=123456789')])
        diagnostics = value['diagnostics']['rejected_candidates']
        self.assertEqual(diagnostics[0]['reason'], 'sale_type_not_literal')
        self.assertEqual(diagnostics[0]['detail'], 'asking_label_missing')
        self.assertEqual(diagnostics[0]['url'], 'https://dealer.example.com/')
        self.assertTrue(diagnostics[0]['url_redacted'])
        encoded = json.dumps(diagnostics)
        for secret in ['PRIVATE12345', 'owner@example.com', '555 1212', 'USD 12,000', 'phone=']:
            self.assertNotIn(secret, encoded)
        text = quote(label='Price')
        value = normalize([candidate(text=text)], [passage(text)])
        self.assertEqual(value['diagnostics']['rejected_candidates'][0]['url'], URLS[0])
        self.assertEqual(value['diagnostics']['rejected_candidates'][0]['title'], 'Caterpillar 2EC25 for sale')

    def test_financing_rental_parts_and_starting_prices_are_excluded(self):
        for extra in ['Monthly payments', 'for rent', 'Parts only', 'Starting at USD 12,000', 'USD 800 per month']:
            text = quote(extra=extra)
            with self.subTest(extra=extra):
                self.assertFalse(normalize([candidate(text=text)], [passage(text)])['comparables'])

    def test_condition_is_machine_label_not_new_tires_or_a_menu(self):
        for text in [quote(condition='Not used'), quote(condition='Used', extra='Does not run.'),
                quote(condition='Used', extra='Condition: New'), quote(condition='Used', extra='Fully refurbished.'),
                quote().replace('Condition: Used.', 'New tires. Used equipment menu.')]:
            with self.subTest(text=text):
                self.assertFalse(normalize([candidate(text=text)], [passage(text)])['comparables'])

    def test_plain_html_label_rows_and_explicit_used_product_sentence_are_supported(self):
        text = quote().replace('Condition: Used', 'Condition Used').replace('Location:', 'Location')
        self.assertEqual(len(normalize([candidate(text=text)], [passage(text)])['comparables']), 1)
        text = quote(condition='Very Good', extra='Used 2EC25 Cat forklift For Sale.')
        self.assertEqual(len(normalize([candidate(text=text)], [passage(text)])['comparables']), 1)
        for wrong in ['Used 2EC30 Cat forklift For Sale.', 'New and used machines for sale.',
                      'Used tires for sale. Caterpillar 2EC25.', 'Used Toyota 2EC25 forklift For Sale.']:
            evidence = quote(condition='Very Good', extra=wrong)
            with self.subTest(wrong=wrong):
                self.assertFalse(normalize([candidate(text=evidence)], [passage(evidence)])['comparables'])

    def test_mico_style_price_is_readable_but_seller_address_does_not_supply_market(self):
        text = ('Cat 14H ASE01868. Asking Price US$ 195,500/-. Location Tacoma WA. Condition Very Good. '
                'Used 14H Cat Motor Grader For Sale: Enclosed cab, air conditioning.')
        identity = {**IDENTITY, 'model': '14H'}
        document = html(text, heading='Cat 14H ASE01868', extras='<select><option>EUR 1</option></select>')
        document += '<footer>Seller: Orlando, Florida, United States</footer>'
        passages = _document_passages(document, URLS[0], identity, [])
        self.assertTrue(passages)
        self.assertNotIn('EUR 1', passages[0]['text'])
        self.assertNotIn('United States', passages[0]['text'])
        value = normalize([candidate(text=text, price='US$ 195,500')], passages, identity)
        self.assertEqual(value['diagnostics']['rejections'], {'market_not_literal': 1})

    def test_unknown_condition_cannot_estimate_even_with_two_matching_sources(self):
        identity = {**IDENTITY, 'condition': None}
        value = normalize([candidate(), candidate(1, price='USD 16,000')],
                          [passage(), passage(quote('USD 16,000'), 1)], identity)
        self.assertEqual(len(value['comparables']), 2)
        self.assertEqual(value['status'], 'insufficient')
        self.assertIn('confirmar si', value['fields']['estimate_missing_info'])

    def test_configuration_must_be_literal_and_match_without_fx_or_unit_conversion(self):
        identity = {**IDENTITY, 'configurations': {'voltage': '36 V'}}
        for extra, configs in [('', []), ('Voltage: 48 V', [Configuration(key='voltage', value='48 V')]),
                ('Voltage: 36 V', [Configuration(key='voltage', value='36 volts')])]:
            text = quote(extra=extra)
            with self.subTest(extra=extra):
                self.assertFalse(normalize([candidate(text=text, configurations=configs)], [passage(text)], identity)['comparables'])
        text = quote(extra='Voltage: 36 V')
        self.assertEqual(len(normalize([candidate(text=text, configurations=[Configuration(key='voltage', value='36 V')])],
                                     [passage(text)], identity)['comparables']), 1)

    def test_markets_currencies_sale_types_and_conditions_are_not_pooled(self):
        variants = [(quote('MXN 16000', country='Mexico'), dict(price='MXN 16000', currency='MXN', market='MX')),
                    (quote('USD 16000', country='Mexico'), dict(price='USD 16000', market='MX')),
                    (quote('USD 16000', label='Sold for'), dict(price='USD 16000', price_type='sold')),
                    (quote('USD 16000', condition='New'), dict(price='USD 16000', condition='new'))]
        for text, kwargs in variants:
            with self.subTest(kwargs=kwargs):
                result = normalize([candidate(), candidate(1, text=text, **kwargs)], [passage(), passage(text, 1)])
                self.assertEqual(result['status'], 'insufficient')
                self.assertLessEqual(len(result['comparables']), 1)

    def test_repeated_urls_same_serial_and_unidentifiable_same_price_do_not_make_two_units(self):
        combinations = [dict(url=URLS[0] + '?utm_source=openai'), dict(_unit_hash='same-unit'),
                        dict(url='https://dealer-one.example.com/equipment/alias')]
        for second in combinations:
            first = passage(_unit_hash='same-unit') if '_unit_hash' in second else passage()
            with self.subTest(second=second):
                result = normalize([candidate(), candidate(1, price='USD 16,000')],
                    [first, passage(quote('USD 16,000'), 1, **second)])
                self.assertEqual(result['status'], 'insufficient')
        self.assertEqual(normalize([candidate(), candidate(1)], [passage(), passage(index=1)])['status'], 'insufficient')

    def test_proof_rejects_tampering_with_price_identity_source_or_status(self):
        baseline = normalize()
        for key, altered in [('status', 'estimated'), ('suggested_price', '999999'),
                             ('identity', {**IDENTITY, 'model': '420F2'}), ('comparables', [])]:
            value = copy.deepcopy(baseline)
            value[key] = altered
            with self.subTest(key=key):
                self.assertFalse(is_validated_estimate(value))


class ValuationIdentityAndDocumentsTests(SimpleTestCase):
    def test_human_identifiers_clear_and_non_operational_status_win_over_fresh_visual(self):
        result = vision()
        for field, value, expected in [('model', None, None), ('condition', 'Nueva', 'new'),
                ('usage_condition', '', None), ('usage_condition', 'Por confirmar', None),
                ('usage_condition', 'Usada', 'used'), ('operating_status', 'No funciona (declarado por el propietario)', 'for_repair')]:
            snapshot = {'data': {field: value}, 'provenance': {field: {'source': 'user', 'review': 'confirmed'}}}
            with self.subTest(field=field, value=value):
                identity = _identity(result, snapshot)
                self.assertEqual(identity['model' if field == 'model' else 'condition'], expected)
        result['data']['usage_condition'] = 'Aparentemente nueva'
        self.assertIsNone(_identity(result, {})['condition'])
        snapshot = {'data': {'engine': 'Call contact owner@example.invalid'},
                    'provenance': {'engine': {'source': 'user'}}}
        self.assertNotIn('engine', _identity(result, snapshot)['configurations'])

    def test_apparent_condition_and_preservation_are_disclosed_without_adjustments(self):
        result = vision()
        result['data']['preservation_condition'] = 'Bueno'
        result['provenance']['preservation_condition'] = {'source': 'visual_proposal', 'review': 'needs_review'}
        value = normalize([candidate(), candidate(1, price='USD 16,000')],
                          [passage(), passage(quote('USD 16,000'), 1)], _identity(result, {}))
        self.assertIn('aparente', value['fields']['estimate_basis'])
        self.assertIn('Bueno', value['fields']['estimate_basis'])
        self.assertEqual(value['suggested_price'], '14000.00')

    def test_html_reader_excludes_navigation_other_models_hidden_and_related_prices(self):
        document = html(extras='<div class="related-products">New model ABC99. Asking price USD 3.</div><p hidden>USD 4</p>')
        passages = _document_passages(document, URLS[0], IDENTITY, [])
        self.assertEqual(len(passages), 1)
        self.assertNotIn('USD 3', passages[0]['text'])
        self.assertNotIn('USD 4', passages[0]['text'])
        self.assertNotIn('New & Used', passages[0]['text'])
        for heading in ['Caterpillar 2EC30', 'Caterpillar 2EC25 IT', 'Toyota 2EC25', 'Caterpillar 2EC25 / 2EC30']:
            with self.subTest(heading=heading):
                self.assertEqual(_document_passages(html(heading=heading), URLS[0], IDENTITY, []), [])

    def test_listing_facts_keep_same_page_condition_and_market_when_far_from_price(self):
        text = ('Location: United States.\nCondition: Used.\n' + ('details ' * 220) +
                '\nAsking price: USD 12,000.')
        facts = _listing_fact_snippets(text)
        self.assertIn('Location: United States.', facts)
        self.assertIn('Condition: Used.', facts)
        pages = [passage(text='Caterpillar 2EC25. Asking price: USD 12,000.', _listing_facts=facts)]
        value = normalize([candidate(text=pages[0]['text'])], pages)
        self.assertEqual(value['comparables'][0]['market'], 'US')
        self.assertEqual(value['comparables'][0]['condition'], 'used')

    def test_other_units_serial_is_hashed_for_dedup_and_current_private_serial_is_never_sent(self):
        first = _document_passages(html(quote(extra='Serial number: OTHERUNIT777')), URLS[0], IDENTITY, ['OWNER123'])
        second = _document_passages(html(quote(extra='Serial number: OTHERUNIT777')), URLS[1], IDENTITY, ['OWNER123'])
        self.assertTrue(first[0]['_unit_hash'])
        self.assertEqual(first[0]['_unit_hash'], second[0]['_unit_hash'])
        self.assertEqual(_document_passages(html(quote(extra='Serial number: OWNER123')), URLS[0], IDENTITY, ['OWNER123']), [])

    def test_direct_transport_rejects_unretrieved_collection_credentials_ip_and_nonhttps(self):
        for url in ['http://dealer.example/item', 'https://127.0.0.1/item', 'https://u:p@dealer.example/item',
                'https://dealer.example/listings/for-sale/caterpillar/2ec25', 'https://www.scribd.com/document/123',
                'https://dealer.example:8443/item']:
            with self.subTest(url=url), self.assertRaises(CatalogFetchError):
                _listing_url(url)
        with patch('portal.valuation._resolve_public_ip') as dns, self.assertRaises(CatalogFetchError):
            _fetch_listing(URLS[0], [], time.monotonic() + 5)
        dns.assert_not_called()
        with patch('portal.valuation._resolve_public_ip', side_effect=CatalogFetchError('dns_not_public')), patch('portal.valuation.urllib3.HTTPSConnectionPool') as connect, self.assertRaises(CatalogFetchError):
            _fetch_listing(URLS[0], URLS, time.monotonic() + 5)
        connect.assert_not_called()

    def test_individual_marketplace_ids_allowed_but_inventory_indexes_rejected(self):
        for path in ['/listing/for-sale/12345/caterpillar-14h-motor-graders',
                     '/listings/for-sale/12345/caterpillar-14h-motor-graders/']:
            url = 'https://www.machinerytrader.com' + path
            with self.subTest(url=url):
                self.assertEqual(_listing_url(url), url)
        for path in ['/listings/for-sale/caterpillar/14h/motor-graders/1045',
                     '/listing/for-sale/caterpillar/14h', '/listings/for-sale/12345/',
                     '/listings/for-sale/12345/caterpillar/other-items']:
            with self.subTest(path=path), self.assertRaises(CatalogFetchError):
                _listing_url('https://www.machinerytrader.com' + path)


class ValuationPipelineTests(SimpleTestCase):
    def test_missing_identity_is_signed_and_never_calls_provider(self):
        client = Mock()
        result, usage = estimate_machine(client, 'gpt-4.1-mini', {'data': {}}, {})
        self.assertEqual(result['status'], 'not_run')
        self.assertTrue(is_validated_estimate(result))
        self.assertIn('marca y modelo', result['fields']['estimate_missing_info'])
        client.responses.create.assert_not_called()
        self.assertEqual(usage.input_tokens, 0)

    def test_pipeline_uses_read_pages_not_search_summary_and_has_bounded_api_requests(self):
        client = provider()
        with patch('portal.valuation._fetch_listing', side_effect=[(html(), URLS[0]), (html(quote('USD 16,000')), URLS[1])]):
            value, usage = estimate_machine(client, 'gpt-4.1-mini', vision(), {})
        self.assertEqual(value['status'], 'estimated')
        self.assertEqual(usage.input_tokens, 8900)
        self.assertEqual(usage.output_tokens, 300)
        self.assertEqual(usage.web_search_calls, 1)
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(client.responses.parse.call_count, 1)
        request = client.responses.create.call_args.kwargs
        self.assertFalse(request['store'])
        self.assertEqual(request['max_tool_calls'], 2)
        self.assertEqual(request['tool_choice'], 'required')
        payload = client.responses.parse.call_args.kwargs['input']
        self.assertNotIn('invented', payload)
        self.assertIn('USD 16,000', payload)
        self.assertNotIn('_unit_hash', payload)

    def test_unreadable_or_price_free_pages_do_not_purchase_parser_or_accept_summary(self):
        client = provider()
        with patch('portal.valuation._fetch_listing', return_value=(html('Call for price.'), URLS[0])):
            value, usage = estimate_machine(client, 'gpt-4.1-mini', vision(), {})
        self.assertEqual(value['status'], 'insufficient')
        self.assertTrue(is_validated_estimate(value))
        client.responses.parse.assert_not_called()
        self.assertEqual(usage.web_search_calls, 1)

    def test_private_values_not_used_in_query_and_owner_serial_url_not_fetched(self):
        result = vision()
        result['data'].update(serial='OWNER123', contact_public='person@example.invalid', notes='PRIVATE-NOTE', location='PRIVATE-LOCATION')
        client = provider([URLS[0] + '/OWNER123'])
        with patch('portal.valuation._fetch_listing') as fetch:
            value, _ = estimate_machine(client, 'gpt-4.1-mini', result, {})
        fetch.assert_not_called()
        request = json.dumps(client.responses.create.call_args.kwargs)
        for private in ('OWNER123', 'person@example.invalid', 'PRIVATE-NOTE', 'PRIVATE-LOCATION'):
            self.assertNotIn(private, request)
            self.assertNotIn(private, json.dumps(value))

    def test_search_and_parse_timeouts_are_accounted_without_leaking_exception_text(self):
        client = provider()
        client.responses.create.side_effect = TimeoutError('SECRET-TOKEN')
        value, usage = estimate_machine(client, 'gpt-4.1-mini', vision(), {})
        self.assertEqual(usage.input_tokens, SEARCH_RESERVATION)
        self.assertNotIn('SECRET-TOKEN', json.dumps(value))
        self.assertTrue(is_validated_estimate(value))
        client = provider()
        client.responses.parse.side_effect = TimeoutError('SECRET-TOKEN')
        with patch('portal.valuation._fetch_listing', return_value=(html(), URLS[0])):
            value, usage = estimate_machine(client, 'gpt-4.1-mini', vision(), {})
        self.assertEqual(usage.input_tokens, 8200 + PARSE_RESERVATION)
        self.assertEqual(usage.estimated_tokens, 8000 + PARSE_RESERVATION)
        self.assertNotIn('SECRET-TOKEN', json.dumps(value))

    def test_revocation_before_search_or_before_parse_stops_outbound_work(self):
        client = provider()
        value, _ = estimate_machine(client, 'gpt-4.1-mini', vision(), {}, allowed=lambda: False)
        self.assertEqual(value['status'], 'not_run')
        client.responses.create.assert_not_called()
        client = provider([URLS[0]])
        allowed = Mock(side_effect=[True, True, False])
        with patch('portal.valuation._fetch_listing', return_value=(html(), URLS[0])):
            value, usage = estimate_machine(client, 'gpt-4.1-mini', vision(), {}, allowed=allowed)
        self.assertEqual(value['status'], 'not_run')
        self.assertTrue(is_validated_estimate(value))
        self.assertGreater(usage.input_tokens, 0)
        client.responses.parse.assert_not_called()

    def test_search_over_reservation_cannot_start_second_call(self):
        client = provider([URLS[0]])
        client.responses.create.return_value.usage.input_tokens = VALUATION_RESERVATION - PARSE_RESERVATION
        with patch('portal.valuation._fetch_listing', return_value=(html(), URLS[0])):
            value, _ = estimate_machine(client, 'gpt-4.1-mini', vision(), {})
        self.assertEqual(value['status'], 'insufficient')
        client.responses.parse.assert_not_called()
        self.assertEqual(value['diagnostics']['stop_reason'], 'parse_reservation_unavailable')
        self.assertNotIn('presupuesto', value['fields']['estimate_missing_info'])

    def test_search_has_27000_including_web_allowance_and_parser_keeps_9000(self):
        self.assertEqual(VALUATION_RESERVATION, 36000)
        self.assertEqual(SEARCH_RESERVATION + PARSE_RESERVATION, VALUATION_RESERVATION)
        for extra, calls in [(0, 1), (1, 0)]:
            client = provider([URLS[0]])
            client.responses.create.return_value.usage.input_tokens = SEARCH_RESERVATION - 8000 - 100 + extra
            with self.subTest(extra=extra), patch('portal.valuation._fetch_listing', return_value=(html(), URLS[0])):
                value, usage = estimate_machine(client, 'gpt-4.1-mini', vision(), {})
            self.assertEqual(client.responses.parse.call_count, calls)
            self.assertTrue(is_validated_estimate(value))
            search = value['diagnostics']['phases'][0]
            self.assertEqual(search['stage'], 'search')
            self.assertEqual(search['input_tokens'] + search['output_tokens'], SEARCH_RESERVATION + extra)
            self.assertEqual(search['measured_input_tokens'], SEARCH_RESERVATION - 8100 + extra)
            self.assertEqual(search['estimated_tokens'], 8000)
            self.assertEqual(value['usage'], usage.as_dict())

    def test_missing_condition_has_priority_over_query_limit_and_unreadable_sources(self):
        result = vision()
        result['data']['usage_condition'] = 'Por confirmar'
        for failure in ('limit', 'unreadable', 'timeout'):
            client = provider([URLS[0]])
            if failure == 'limit':
                client.responses.create.return_value.usage.input_tokens = SEARCH_RESERVATION + 1
            if failure == 'timeout':
                client.responses.create.side_effect = TimeoutError('PRIVATE-ERROR')
            document = html('Call for price') if failure == 'unreadable' else html()
            with self.subTest(failure=failure), patch('portal.valuation._fetch_listing', return_value=(document, URLS[0])):
                value, usage = estimate_machine(client, 'gpt-4.1-mini', result, {})
            self.assertEqual(value['status'], 'insufficient')
            self.assertIn('confirmar si la máquina', value['fields']['estimate_missing_info'])
            self.assertNotIn('presupuesto', value['fields']['estimate_missing_info'])
            self.assertNotIn('PRIVATE-ERROR', json.dumps(value))
            self.assertIsNone(value['suggested_price'])
            self.assertTrue(is_validated_estimate(value))
            if failure == 'timeout':
                self.assertEqual(usage.estimated_tokens, SEARCH_RESERVATION)
                self.assertEqual(value['diagnostics']['phases'][0]['status'], 'outcome_unknown')
                self.assertEqual(value['diagnostics']['phases'][0]['measured_input_tokens'], 0)

    def test_each_phase_reports_measured_and_estimated_usage_after_parse_timeout(self):
        client = provider([URLS[0]])
        client.responses.parse.side_effect = TimeoutError('SECRET-ERROR')
        with patch('portal.valuation._fetch_listing', return_value=(html(), URLS[0])):
            value, usage = estimate_machine(client, 'gpt-4.1-mini', vision(), {})
        stages = value['diagnostics']['phases']
        self.assertEqual([stage['stage'] for stage in stages], ['search', 'parse'])
        self.assertEqual(stages[0]['measured_input_tokens'], 200)
        self.assertEqual(stages[0]['estimated_tokens'], 8000)
        self.assertEqual(stages[1]['input_tokens'], PARSE_RESERVATION)
        self.assertEqual(stages[1]['estimated_tokens'], PARSE_RESERVATION)
        self.assertEqual(stages[1]['status'], 'outcome_unknown')
        self.assertEqual(sum(stage['input_tokens'] for stage in stages), usage.input_tokens)
        self.assertEqual(sum(stage['output_tokens'] for stage in stages), usage.output_tokens)

    def test_consent_revoked_after_parse_discards_prices_but_keeps_all_usage(self):
        client = provider([URLS[0]])
        with patch('portal.valuation._fetch_listing', return_value=(html(), URLS[0])):
            value, usage = estimate_machine(client, 'gpt-4.1-mini', vision(), {},
                                           allowed=Mock(side_effect=[True, True, True, False]))
        self.assertEqual(value['status'], 'not_run')
        self.assertFalse(value['comparables'])
        self.assertIsNone(value['suggested_price'])
        self.assertEqual(usage.input_tokens + usage.output_tokens, 9200)
        self.assertTrue(is_validated_estimate(value))

    def test_parser_prompt_is_byte_bounded_even_for_multibyte_page_text(self):
        client = provider()
        text = quote(extra='漢字' * 300)
        with patch('portal.valuation._fetch_listing', return_value=(html(text), URLS[0])):
            estimate_machine(client, 'gpt-4.1-mini', vision(), {})
        request = client.responses.parse.call_args.kwargs
        self.assertLessEqual(len(request['input'].encode()) + len(request['instructions'].encode()), 6000)
        self.assertLessEqual(6000 + request['max_output_tokens'], PARSE_RESERVATION)
