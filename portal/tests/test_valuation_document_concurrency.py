"""Concurrent downloads retain deterministic, bounded, directly checked evidence."""
import json
import threading
import time
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from portal.research_fetch import CatalogFetchError
from portal.tests.test_valuation import candidate, html, provider, quote, vision
from portal.valuation import (
    ComparableCandidates, MAX_CONCURRENT_DOCUMENTS, MAX_DOCUMENT_ATTEMPTS,
    MAX_DOCUMENTS, _fetch_document_batch, estimate_machine, is_validated_estimate,
)


class ValuationDocumentConcurrencyTests(SimpleTestCase):
    def test_independent_reads_overlap_but_evidence_order_and_auth_thread_do_not_change(self):
        rendezvous = threading.Barrier(MAX_CONCURRENT_DOCUMENTS)
        released = [threading.Event() for _ in range(MAX_CONCURRENT_DOCUMENTS)]
        completions, auth_threads = [], []
        caller = threading.get_ident()
        deadline = time.monotonic() + 5

        def fetch(index, request_deadline):
            self.assertEqual(request_deadline, deadline)
            self.assertNotEqual(threading.get_ident(), caller)
            rendezvous.wait(timeout=2)
            if index < MAX_CONCURRENT_DOCUMENTS - 1:
                self.assertTrue(released[index + 1].wait(timeout=2))
            completions.append(index)
            released[index].set()
            return f'document-{index}'

        def allowed():
            auth_threads.append(threading.get_ident())
            return True

        outcomes = _fetch_document_batch(fetch,
            [(index, deadline) for index in range(MAX_CONCURRENT_DOCUMENTS)],
            allowed=allowed, deadline=deadline)
        self.assertEqual(completions, list(reversed(range(MAX_CONCURRENT_DOCUMENTS))))
        self.assertEqual(outcomes, [(f'document-{index}', None) for index in range(MAX_CONCURRENT_DOCUMENTS)])
        self.assertEqual(set(auth_threads), {caller})

    def test_no_download_starts_after_deadline_or_without_authorization(self):
        fetch = Mock()
        self.assertEqual(_fetch_document_batch(fetch, [('one',)], allowed=lambda: True,
                                              deadline=time.monotonic() - 1), [])
        self.assertIsNone(_fetch_document_batch(fetch, [('one',)], allowed=lambda: False,
                                               deadline=time.monotonic() + 5))
        fetch.assert_not_called()

    def test_consent_revocation_during_download_discards_inflight_documents(self):
        permitted = threading.Event()
        permitted.set()

        def fetch():
            permitted.clear()
            return 'private result must not be parsed'

        self.assertIsNone(_fetch_document_batch(fetch, [()], allowed=permitted.is_set,
                                               deadline=time.monotonic() + 5))

    def test_six_successful_listings_keep_search_order_and_the_same_price_evidence(self):
        urls = [f'https://dealer-{index}.example.com/equipment/unit-{index}' for index in range(20)]
        fields = [candidate(index, price=f'USD {12 + index},000') for index in range(MAX_DOCUMENTS)]
        client = provider(urls=urls, parsed=ComparableCandidates(fields=fields))
        seen = []

        def fetch(url, retrieved, deadline):
            self.assertIn(url, retrieved)
            self.assertTrue(set(retrieved).issubset(urls))
            seen.append((url, deadline))
            index = urls.index(url)
            return html(quote(f'USD {12 + index},000')), url

        with patch('portal.valuation._fetch_listing', side_effect=fetch):
            value, usage = estimate_machine(client, 'gpt-5.6-luna', vision())
        self.assertEqual(len(seen), MAX_DOCUMENTS)
        self.assertEqual(len({deadline for _, deadline in seen}), 1)
        payload = json.loads(client.responses.parse.call_args.kwargs['input'])
        self.assertEqual([entry['url'] for entry in payload['passages']], urls[:MAX_DOCUMENTS])
        self.assertEqual(value['status'], 'estimated')
        self.assertEqual(value['fields']['estimate_min'], '12000.00')
        self.assertEqual(value['fields']['estimate_max'], '17000.00')
        self.assertEqual(value['fields']['estimate_currency'], 'USD')
        self.assertEqual(len(value['comparables']), MAX_DOCUMENTS)
        self.assertTrue(is_validated_estimate(value))
        self.assertEqual(usage.web_search_calls, 1)
        self.assertEqual([phase['stage'] for phase in value['diagnostics']['phases']],
                         ['search', 'documents', 'parse'])
        self.assertEqual(value['diagnostics']['phases'][1]['input_tokens'], 0)

    def test_blocked_sites_are_replaced_without_exceeding_attempt_or_evidence_limits(self):
        urls = [f'https://dealer-{index}.example.com/equipment/unit-{index}' for index in range(20)]
        client = provider(urls=urls)
        attempted = []

        def fetch(url, retrieved, deadline):
            attempted.append(url)
            index = urls.index(url)
            if index < MAX_DOCUMENT_ATTEMPTS - MAX_DOCUMENTS:
                raise CatalogFetchError('blocked')
            return html(), url

        with patch('portal.valuation._fetch_listing', side_effect=fetch):
            value, _ = estimate_machine(client, 'gpt-5.6-luna', vision())
        self.assertEqual(len(attempted), MAX_DOCUMENT_ATTEMPTS)
        statuses = [entry['status'] for entry in value['diagnostics']['document_attempts']]
        self.assertEqual(statuses.count('read'), MAX_DOCUMENTS)
        self.assertEqual(statuses.count('unavailable'), MAX_DOCUMENT_ATTEMPTS - MAX_DOCUMENTS)
        self.assertEqual(set(attempted), set(urls[:MAX_DOCUMENT_ATTEMPTS]))

    def test_unsafe_search_results_are_excluded_before_any_parallel_dispatch(self):
        urls = ['https://127.0.0.1/equipment/unit', 'https://dealer.example.com/search?q=cat',
                'http://dealer.example.com/equipment/unit']
        client = provider(urls=urls)
        with patch('portal.valuation._fetch_listing') as fetch:
            value, _ = estimate_machine(client, 'gpt-5.6-luna', vision())
        fetch.assert_not_called()
        client.responses.parse.assert_not_called()
        self.assertEqual(value['status'], 'insufficient')
