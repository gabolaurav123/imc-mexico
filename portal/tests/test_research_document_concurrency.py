"""Two technical pages overlap without changing selection or evidence order."""
import threading
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from portal.research_documents import collect_document_fields
from portal.research_fetch import CatalogFetchError
from portal.tests.test_research_documents import IDENTITY, TITLE, URL, document


OTHER_URL = 'https://h-cpc.cat.com/cmms/v2?f=product&it=product&pid=123'


class ResearchDocumentConcurrencyTests(SimpleTestCase):
    def test_two_selected_hosts_overlap_keep_order_and_parse_only_on_caller_thread(self):
        rendezvous = threading.Barrier(2)
        second_finished = threading.Event()
        caller = threading.get_ident()
        completed, parsed, auth_threads = [], [], []
        retrieved = [{'url': URL, 'title': TITLE}, {'url': URL + '-alternative', 'title': TITLE},
                     {'url': OTHER_URL, 'title': TITLE}]
        sources, passages, titles = [], [], {}

        def allowed():
            auth_threads.append(threading.get_ident())
            return True

        def fetch(url, *, retrieved_urls):
            self.assertNotEqual(threading.get_ident(), caller)
            self.assertEqual(retrieved_urls, [source['url'] for source in retrieved])
            rendezvous.wait(timeout=2)
            if url == URL:
                self.assertTrue(second_finished.wait(timeout=2))
            completed.append(url)
            if url == OTHER_URL:
                second_finished.set()
            return SimpleNamespace(html='table', final_url=url)

        def parse(html, url, identity):
            self.assertEqual(threading.get_ident(), caller)
            self.assertEqual(identity, IDENTITY)
            parsed.append(url)
            return document(url)

        with patch('portal.research_documents.fetch_catalog_html', side_effect=fetch) as fetcher, \
                patch('portal.research_documents.parse_catalog_html', side_effect=parse):
            fields, attempts, cancelled = collect_document_fields(
                IDENTITY, retrieved, sources, passages, titles, allowed)
        self.assertFalse(cancelled)
        self.assertEqual(fetcher.call_count, 2)
        self.assertEqual(completed, [OTHER_URL, URL])
        self.assertEqual(parsed, [URL, OTHER_URL])
        self.assertEqual([field.source_url for field in fields], parsed)
        self.assertEqual([source['url'] for source in sources], parsed)
        self.assertEqual([passage['source_url'] for passage in passages], parsed)
        self.assertEqual([passage['passage_index'] for passage in passages], [0, 1])
        self.assertEqual([item['status'] for item in attempts], ['matched', 'matched'])
        self.assertEqual(set(auth_threads), {caller})

    def test_revocation_during_download_discards_both_and_joins_before_returning(self):
        rendezvous = threading.Barrier(2)
        permitted = threading.Event()
        permitted.set()
        completed = []
        sources, passages, titles = [], [], {}

        def fetch(url, **kwargs):
            rendezvous.wait(timeout=2)
            permitted.clear()
            completed.append(url)
            return SimpleNamespace(html='table', final_url=url)

        with patch('portal.research_documents.fetch_catalog_html', side_effect=fetch), \
                patch('portal.research_documents.parse_catalog_html') as parse:
            fields, attempts, cancelled = collect_document_fields(IDENTITY,
                [{'url': URL, 'title': TITLE}, {'url': OTHER_URL, 'title': TITLE}],
                sources, passages, titles, permitted.is_set)
        self.assertTrue(cancelled)
        self.assertEqual(set(completed), {URL, OTHER_URL})
        self.assertEqual(fields, [])
        self.assertEqual((sources, passages, titles), ([], [], {}))
        self.assertEqual(len(attempts), 2)
        parse.assert_not_called()

    def test_denied_authorization_prevents_all_downloads(self):
        with patch('portal.research_documents.fetch_catalog_html') as fetch:
            outcome = collect_document_fields(IDENTITY,
                [{'url': URL, 'title': TITLE}, {'url': OTHER_URL, 'title': TITLE}],
                [], [], {}, lambda: False)
        self.assertEqual(outcome, ([], [], True))
        fetch.assert_not_called()

    def test_one_download_or_parse_failure_does_not_drop_the_other_document(self):
        for mode in ('fetch_timeout', 'fetch_unexpected', 'parse_failure'):
            with self.subTest(mode=mode):
                def fetch(url, **kwargs):
                    if url == URL and mode == 'fetch_timeout':
                        raise CatalogFetchError('timeout')
                    if url == URL and mode == 'fetch_unexpected':
                        raise RuntimeError('PRIVATE RESPONSE')
                    return SimpleNamespace(html='table', final_url=url)

                def parse(html, url, identity):
                    if url == URL and mode == 'parse_failure':
                        raise ValueError('PRIVATE RESPONSE')
                    return document(url)

                sources, passages, titles = [], [], {}
                with patch('portal.research_documents.fetch_catalog_html', side_effect=fetch), \
                        patch('portal.research_documents.parse_catalog_html', side_effect=parse):
                    fields, attempts, cancelled = collect_document_fields(IDENTITY,
                        [{'url': URL, 'title': TITLE}, {'url': OTHER_URL, 'title': TITLE}],
                        sources, passages, titles)
                self.assertFalse(cancelled)
                self.assertEqual([field.source_url for field in fields], [OTHER_URL])
                self.assertEqual([attempt['status'] for attempt in attempts], ['unavailable', 'matched'])
                self.assertEqual(attempts[0]['reason'], 'timeout' if mode == 'fetch_timeout' else 'document_parse_failed')
                self.assertNotIn('PRIVATE RESPONSE', str(attempts))

    def test_unsupported_and_duplicate_urls_do_not_add_parallel_downloads(self):
        retrieved = [{'url': URL, 'title': TITLE}, {'url': URL, 'title': TITLE},
                     {'url': 'http://www.ritchiespecs.com/model/caterpillar-420f2', 'title': TITLE},
                     {'url': 'https://127.0.0.1/model/caterpillar-420f2', 'title': TITLE}]
        with patch('portal.research_documents.fetch_catalog_html',
                   return_value=SimpleNamespace(html='table', final_url=URL)) as fetch, \
                patch('portal.research_documents.parse_catalog_html', return_value=document()):
            fields, attempts, cancelled = collect_document_fields(IDENTITY, retrieved, [], [], {})
        self.assertFalse(cancelled)
        self.assertEqual((len(fields), len(attempts), fetch.call_count), (1, 1, 1))
        self.assertEqual(fetch.call_args.args, (URL,))
