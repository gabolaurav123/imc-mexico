import gzip
import io
import socket
import ssl
import time
from unittest.mock import Mock, patch
import zlib

from django.test import SimpleTestCase
import urllib3

from portal.research_fetch import (
    CatalogFetchError, MAX_BYTES, fetch_catalog_html, supports_catalog_url,
    _resolve_public_ip,
)


CAT = 'https://h-cpc.cat.com/cmms/v2?cid=406&f=product&gid=270&it=product&lid=en&nc=1&pid=1000001746&sc=R460'
PRODUCT = 'https://www.cat.com/en_US/products/new/equipment/backhoe-loaders/example.html'
RITCHIE = 'https://www.ritchiespecs.com/model/caterpillar-420f2-it'
IP = '93.184.216.34'


class FakeResponse:
    def __init__(self, body=b'<html><h1>Test machine</h1></html>', status=200, headers=None):
        self.status = status
        self.headers = {'Content-Type': 'text/html; charset=utf-8', **(headers or {})}
        self.body = io.BytesIO(body)
        self.closed = False
        self.connection = Mock()
        self.read_count = 0

    def read1(self, amount, decode_content=False):
        assert decode_content is False
        self.read_count += 1
        return self.body.read(amount)

    def close(self):
        self.closed = True


class CatalogFetchTests(SimpleTestCase):
    def setUp(self):
        self.dns = patch('portal.research_fetch.socket.getaddrinfo', return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', (IP, 443))]).start()
        self.pool_constructor = patch('portal.research_fetch.urllib3.HTTPSConnectionPool').start()
        self.addCleanup(patch.stopall)
        self.pool = self.pool_constructor.return_value.__enter__.return_value

    def fetch(self, response, url=CAT):
        self.pool.urlopen.return_value = response
        return fetch_catalog_html(url, retrieved_urls=[url])

    def assert_code(self, code, operation):
        with self.assertRaises(CatalogFetchError) as captured:
            operation()
        self.assertEqual(captured.exception.code, code)
        self.assertEqual(str(captured.exception), code)

    def test_exact_product_routes_and_query_allowlist(self):
        for url in (CAT, RITCHIE, RITCHIE.replace('.com/', '.com:443/')):
            with self.subTest(url=url):
                self.assertTrue(supports_catalog_url(url))
        for url in (PRODUCT, 'https://lectura-specs.com/en/model/example',
                    'https://www.cat.com/login', 'https://cat.com/en_US/products/new/x',
                    PRODUCT + '?next=https://private.example/', PRODUCT + '#',
                    PRODUCT.replace('/new/', '/new/../'), PRODUCT.replace('/new/', '/new/%2e%2e/'),
                    PRODUCT.replace('/new/', '/new//'), 'http://' + PRODUCT[8:],
                    PRODUCT.replace('.com/', '.com.evil.example/'),
                    PRODUCT.replace('www.cat.com', 'user:password@www.cat.com'),
                    PRODUCT.replace('.com/', '.com:444/'),
                    'https://127.0.0.1/model/test', 'https://[::1]/model/test',
                    CAT + '&redirect=http://127.0.0.1', CAT + '&pid=2',
                    CAT.replace('it=product', 'it=login'), CAT.replace('pid=1000001746', 'pid=PRIVATE'),
                    CAT.replace('lid=en', 'lid=owner@example.invalid'),
                    PRODUCT + '\n', PRODUCT.replace('.com/', '.com\\/'), None, {}):
            with self.subTest(url=url):
                self.assertFalse(supports_catalog_url(url))
        self.dns.assert_not_called()
        self.pool_constructor.assert_not_called()

    def test_a_supported_user_url_cannot_be_fetched_unless_returned_by_tool(self):
        self.assert_code('not_retrieved', lambda: fetch_catalog_html(CAT, retrieved_urls=[PRODUCT]))
        self.assert_code('not_retrieved', lambda: fetch_catalog_html(CAT, retrieved_urls=CAT))
        self.assert_code('not_retrieved', lambda: fetch_catalog_html(CAT, retrieved_urls=123))
        self.dns.assert_not_called()
        self.pool_constructor.assert_not_called()

    def test_only_known_tool_attribution_is_stripped_after_exact_retrieval_check(self):
        for base in (CAT, RITCHIE):
            for attribution in ('openai', 'chatgpt.com'):
                with self.subTest(base=base, attribution=attribution):
                    separator = '&' if '?' in base else '?'
                    original = base + separator + 'utm_source=' + attribution
                    self.assertTrue(supports_catalog_url(original))
                    page = self.fetch(FakeResponse(), original)
                    self.assertEqual(page.final_url, base)
                    self.assertNotIn('utm_source', self.pool.urlopen.call_args.args[1])
                    self.assert_code('not_retrieved', lambda: fetch_catalog_html(original, retrieved_urls=[base]))
        for query in ('utm_source=owner', 'utm_source=openai&contact=secret',
                      'utm_source=openai&utm_source=chatgpt.com', 'utm_medium=openai'):
            with self.subTest(query=query):
                self.assertFalse(supports_catalog_url(RITCHIE + '?' + query))

    def test_connects_only_to_validated_ip_with_original_tls_identity_and_no_auth(self):
        response = FakeResponse('<html>Especificación técnica</html>'.encode())
        page = self.fetch(response)
        self.assertEqual(page.html, '<html>Especificación técnica</html>')
        self.assertEqual(page.final_url, CAT)
        args, kwargs = self.pool_constructor.call_args
        self.assertEqual(args, (IP,))
        self.assertEqual(kwargs['port'], 443)
        self.assertEqual(kwargs['assert_hostname'], 'h-cpc.cat.com')
        self.assertEqual(kwargs['server_hostname'], 'h-cpc.cat.com')
        self.assertEqual(kwargs['cert_reqs'], ssl.CERT_REQUIRED)
        self.assertTrue(kwargs['ca_certs'])
        self.assertNotIn('_proxy', kwargs)
        request = self.pool.urlopen.call_args
        self.assertEqual(request.args[0], 'GET')
        self.assertTrue(request.args[1].startswith('/cmms/v2?'))
        self.assertFalse(request.kwargs['redirect'])
        self.assertFalse(request.kwargs['retries'])
        self.assertFalse(request.kwargs['preload_content'])
        self.assertEqual(request.kwargs['headers']['Host'], 'h-cpc.cat.com')
        self.assertFalse({'Cookie', 'Authorization', 'Referer'} & request.kwargs['headers'].keys())
        self.assertTrue(response.closed)
        self.dns.assert_called_once()

    def test_two_redirects_are_validated_without_cookies_or_redirect_body_reads(self):
        first = FakeResponse(status=302, headers={'Location': RITCHIE + '-alternate', 'Set-Cookie': 'secret=value'})
        second = FakeResponse(status=301, headers={'Location': RITCHIE})
        final = FakeResponse()
        self.pool.urlopen.side_effect = [first, second, final]
        page = fetch_catalog_html(CAT, retrieved_urls=[CAT])
        self.assertEqual(page.final_url, RITCHIE)
        self.assertEqual(self.dns.call_count, 3)
        self.assertEqual((first.read_count, second.read_count), (0, 0))
        self.assertTrue(all(response.closed for response in (first, second, final)))
        for call in self.pool.urlopen.call_args_list:
            self.assertNotIn('Cookie', call.kwargs['headers'])

    def test_rejected_redirects_never_resolve_or_connect_to_the_destination(self):
        for destination in ('http://127.0.0.1/', 'https://www.cat.com/login',
                            'https://www.cat.com.evil.example/en_US/products/new/a',
                            RITCHIE + '#private', RITCHIE + '#', '\n' + RITCHIE,
                            'https://user:pass@www.ritchiespecs.com/model/a'):
            with self.subTest(destination=destination):
                self.dns.reset_mock()
                self.pool_constructor.reset_mock()
                response = FakeResponse(status=302, headers={'Location': destination})
                self.assert_code('unsupported_url', lambda: self.fetch(response))
                self.assertEqual(self.dns.call_count, 1)
                self.assertEqual(self.pool_constructor.call_count, 1)
                self.assertTrue(response.closed)

    def test_redirect_limit_stops_after_three_http_responses(self):
        responses = [FakeResponse(status=302, headers={'Location': RITCHIE}) for _ in range(3)]
        self.pool.urlopen.side_effect = responses
        self.assert_code('too_many_redirects', lambda: fetch_catalog_html(CAT, retrieved_urls=[CAT]))
        self.assertEqual(self.pool.urlopen.call_count, 3)
        self.assertTrue(all(response.closed for response in responses))

    def test_private_mixed_or_invalid_dns_never_reaches_the_network_pool(self):
        for address in ('127.0.0.1', '10.0.0.1', '169.254.169.254', '192.168.1.1',
                        '::1', 'fc00::1', 'fe80::1', '224.0.0.1', 'bad-address'):
            with self.subTest(address=address):
                self.dns.return_value = [
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', (IP, 443)),
                    (socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443)),
                ]
                self.assert_code('dns_not_public', lambda: self.fetch(FakeResponse()))
        self.pool_constructor.assert_not_called()

    def test_dns_is_checked_again_at_a_redirect_and_rebinding_cannot_reuse_host_resolution(self):
        self.dns.side_effect = [
            [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (IP, 443))],
            [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))],
        ]
        response = FakeResponse(status=302, headers={'Location': RITCHIE})
        self.assert_code('dns_not_public', lambda: self.fetch(response))
        self.assertEqual(self.pool_constructor.call_count, 1)
        self.assertEqual(self.pool_constructor.call_args.args, (IP,))
        self.assertTrue(response.closed)

    def test_dns_error_and_deadline_are_bounded_and_redacted(self):
        self.dns.side_effect = socket.gaierror('PRIVATE-URL-AND-TOKEN')
        self.assert_code('dns_failed', lambda: self.fetch(FakeResponse()))
        with patch('portal.research_fetch.threading.Thread'):
            self.assert_code('dns_timeout', lambda: _resolve_public_ip('www.cat.com', time.monotonic() + 0.01))
        self.pool_constructor.assert_not_called()

    def test_forbidden_status_and_non_html_are_rejected_without_reading_a_body(self):
        for status in (401, 403, 404, 429, 500):
            with self.subTest(status=status):
                response = FakeResponse(status=status)
                self.assert_code('http_status', lambda: self.fetch(response))
                self.assertEqual(response.read_count, 0)
                self.assertTrue(response.closed)
        response = FakeResponse(headers={'Content-Type': 'application/pdf'})
        self.assert_code('not_html', lambda: self.fetch(response))
        self.assertEqual(response.read_count, 0)

    def test_announced_and_streamed_size_limits_do_not_return_partial_html(self):
        response = FakeResponse(headers={'Content-Length': str(MAX_BYTES + 1)})
        self.assert_code('too_large', lambda: self.fetch(response))
        self.assertEqual(response.read_count, 0)
        response = FakeResponse(b'a' * (MAX_BYTES + 1))
        self.assert_code('too_large', lambda: self.fetch(response))
        self.assertTrue(response.closed)
        self.assertEqual(len(self.fetch(FakeResponse(b'a' * MAX_BYTES)).html), MAX_BYTES)

    def test_compressed_html_is_bounded_after_decompression(self):
        small = gzip.compress(b'<html>Machine specs</html>')
        self.assertEqual(self.fetch(FakeResponse(small, headers={'Content-Encoding': 'gzip'})).html,
                         '<html>Machine specs</html>')
        bomb = gzip.compress(b'a' * (MAX_BYTES + 1))
        response = FakeResponse(bomb, headers={'Content-Encoding': 'gzip', 'Content-Length': str(len(bomb))})
        self.assertLess(len(bomb), MAX_BYTES)
        self.assert_code('too_large', lambda: self.fetch(response))
        self.assertTrue(response.closed)

    def test_malformed_encoding_and_length_are_fixed_errors_and_deflate_is_supported(self):
        body = b'<html>Machine</html>'
        response = FakeResponse(zlib.compress(body), headers={'Content-Encoding': 'deflate'})
        self.assertEqual(self.fetch(response).html, body.decode())
        for response, code in (
                (FakeResponse(headers={'Content-Length': '-1'}), 'invalid_length'),
                (FakeResponse(headers={'Content-Encoding': 'br'}), 'unsupported_encoding'),
                (FakeResponse(gzip.compress(body)[:-3], headers={'Content-Encoding': 'gzip'}), 'invalid_encoding'),
                (FakeResponse(b'not gzip', headers={'Content-Encoding': 'gzip'}), 'fetch_failed'),
                (FakeResponse(b''), 'empty_body')):
            with self.subTest(code=code):
                self.assert_code(code, lambda: self.fetch(response))
                self.assertTrue(response.closed)

    def test_timeout_and_tls_errors_never_expose_request_text(self):
        for error, code in ((urllib3.exceptions.ReadTimeoutError(None, CAT + 'PRIVATE', 'secret'), 'timeout'),
                            (urllib3.exceptions.SSLError('PRIVATE-URL-OR-CERT'), 'fetch_failed')):
            with self.subTest(error=type(error).__name__):
                self.pool.urlopen.side_effect = error
                self.assert_code(code, lambda: fetch_catalog_html(CAT, retrieved_urls=[CAT]))

    def test_total_deadline_includes_body_reads(self):
        response = FakeResponse()
        with patch('portal.research_fetch.time.monotonic', side_effect=[0, 0, 0, 0, 0, 16]):
            self.assert_code('timeout', lambda: self.fetch(response))
        self.assertTrue(response.closed)
