"""Bounded reading of public product URLs already returned by web search.

This module neither discovers URLs nor authenticates to websites. Callers own
consent checks and the limit on pages per research job. HTML is untrusted data,
never executable UI, and successful transport does not validate a specification.
"""
from dataclasses import dataclass
from email.message import Message
import ipaddress
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
import zlib

import certifi
import urllib3


MAX_BYTES = 1024 * 1024
MAX_REDIRECTS = 2
TOTAL_TIMEOUT = 15.0
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
DNS_TIMEOUT = 3.0
CHUNK_SIZE = 16384
ALLOWED_HOSTS = frozenset({'h-cpc.cat.com', 'www.ritchiespecs.com'})


@dataclass(frozen=True, slots=True)
class CatalogPage:
    html: str
    final_url: str


class CatalogFetchError(ValueError):
    """A fixed diagnostic code; never includes provider text or a request URL."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _validated_url(url):
    if (not isinstance(url, str) or not url or len(url) > 1600
            or any(char.isspace() or ord(char) < 32 for char in url)
            or '\\' in url or '#' in url):
        raise CatalogFetchError('unsupported_url')
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (parsed.scheme != 'https' or host not in ALLOWED_HOSTS
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 443}):
            raise CatalogFetchError('unsupported_url')
        # Avoid encoded separators, dot traversal and ambiguous path handling.
        path = parsed.path
        if (not re.fullmatch(r'/[A-Za-z0-9._~/-]+', path) or '//' in path
                or any(part in {'.', '..'} for part in path.split('/'))):
            raise CatalogFetchError('unsupported_url')
        # Public H-CPC links can start with ?&f=product. Empty leading query
        # separators carry no value; the remaining key/value policy is strict.
        pairs = parse_qsl(parsed.query.lstrip('&'), keep_blank_values=True, strict_parsing=True)
        attribution = [(key, value) for key, value in pairs if key == 'utm_source']
        if attribution:
            if len(attribution) != 1 or attribution[0][1] not in {'openai', 'chatgpt.com'}:
                raise CatalogFetchError('unsupported_url')
            pairs = [(key, value) for key, value in pairs if key != 'utm_source']
        if host == 'h-cpc.cat.com':
            if path != '/cmms/v2':
                raise CatalogFetchError('unsupported_url')
            params = dict(pairs)
            if (len(pairs) != len(params) or not {'f', 'it', 'pid'} <= params.keys()
                    or params.keys() - {'cid', 'f', 'gid', 'it', 'lid', 'nc', 'pid', 'sc'}
                    or params['f'] != 'product' or params['it'] != 'product'):
                raise CatalogFetchError('unsupported_url')
            for key, value in pairs:
                pattern = (r'[0-9]{1,12}' if key in {'cid', 'gid', 'pid', 'nc'} else
                           r'[a-z]{2}(?:[-_][A-Za-z]{2})?' if key == 'lid' else
                           r'[A-Za-z0-9_-]{1,24}')
                if not re.fullmatch(pattern, value):
                    raise CatalogFetchError('unsupported_url')
        else:
            prefix = '/model/'
            if pairs or not path.startswith(prefix) or len(path) == len(prefix):
                raise CatalogFetchError('unsupported_url')
        # Strip only known web-tool attribution. Other query arguments retain
        # their strict route-specific validation, including duplicate rejection.
        return urlunsplit(('https', host, path, urlencode(pairs), ''))
    except (TypeError, ValueError) as exc:
        if isinstance(exc, CatalogFetchError):
            raise
        raise CatalogFetchError('unsupported_url') from None


def supports_catalog_url(url):
    """Pure candidate predicate. It does not authorize a user-supplied URL."""
    try:
        _validated_url(url)
        return True
    except CatalogFetchError:
        return False


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CatalogFetchError('timeout')
    return remaining


def _resolve_public_ip(host, deadline):
    # getaddrinfo has no portable timeout. A daemon resolver cannot stall the
    # worker deadline; its result alone cannot initiate an HTTP connection.
    results = queue.Queue(maxsize=1)

    def resolve():
        try:
            results.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError:
            results.put(None)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        addresses = results.get(timeout=min(DNS_TIMEOUT, _remaining(deadline)))
    except queue.Empty:
        raise CatalogFetchError('dns_timeout') from None
    if not addresses:
        raise CatalogFetchError('dns_failed')
    public = []
    for family, _, _, _, address in addresses:
        try:
            ip = ipaddress.ip_address(address[0])
        except (ValueError, IndexError, TypeError):
            raise CatalogFetchError('dns_not_public') from None
        if (family not in {socket.AF_INET, socket.AF_INET6} or not ip.is_global
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            raise CatalogFetchError('dns_not_public')
        public.append(str(ip))
    _remaining(deadline)
    # Prefer IPv4 when both families exist; use only this checked numeric IP.
    return next((ip for ip in public if ':' not in ip), public[0])


def _read_html(response, deadline):
    content_type = Message()
    content_type['content-type'] = response.headers.get('Content-Type', '')
    if content_type.get_content_type() not in {'text/html', 'application/xhtml+xml'}:
        raise CatalogFetchError('not_html')
    announced = response.headers.get('Content-Length')
    if announced is not None:
        if not announced.isdigit():
            raise CatalogFetchError('invalid_length')
        if int(announced) > MAX_BYTES:
            raise CatalogFetchError('too_large')
    encoding = response.headers.get('Content-Encoding', '').strip().lower()
    if encoding not in {'', 'identity', 'gzip', 'deflate'}:
        raise CatalogFetchError('unsupported_encoding')
    decoder = zlib.decompressobj(31 if encoding == 'gzip' else zlib.MAX_WBITS) if encoding in {'gzip', 'deflate'} else None
    parts, decoded_size, wire_size = [], 0, 0
    while True:
        remaining = _remaining(deadline)
        connection = response.connection
        if connection is not None and connection.sock is not None:
            connection.sock.settimeout(min(READ_TIMEOUT, remaining))
        # Raw read1 avoids an unbounded decoded/compressed stream read. Each
        # decoder call can produce at most the remaining byte allowance + 1.
        chunk = response.read1(CHUNK_SIZE, decode_content=False)
        _remaining(deadline)
        if not chunk:
            break
        wire_size += len(chunk)
        if wire_size > MAX_BYTES:
            raise CatalogFetchError('too_large')
        output = decoder.decompress(chunk, MAX_BYTES - decoded_size + 1) if decoder else chunk
        decoded_size += len(output)
        if decoded_size > MAX_BYTES or (decoder and decoder.unconsumed_tail):
            raise CatalogFetchError('too_large')
        parts.append(output)
    if decoder and (not decoder.eof or decoder.unused_data):
        raise CatalogFetchError('invalid_encoding')
    if not decoded_size:
        raise CatalogFetchError('empty_body')
    charset = content_type.get_content_charset() or 'utf-8'
    try:
        return b''.join(parts).decode(charset, errors='replace')
    except (LookupError, UnicodeError):
        raise CatalogFetchError('unsupported_charset') from None


def fetch_catalog_html(url, *, retrieved_urls):
    """Read one allowlisted web-tool result; no cookies, proxies or retries.

    ``retrieved_urls`` must come from the actual tool's returned sources, not
    advertiser input. Redirects need not be separately indexed, but every hop
    must pass the same route policy and public-DNS check. The numeric-IP pool
    pins the connection while hostname assertion and SNI preserve TLS checks.
    """
    try:
        retrieved = (isinstance(url, str) and not isinstance(retrieved_urls, (str, bytes))
                     and retrieved_urls is not None and url in retrieved_urls)
    except (TypeError, ValueError):
        retrieved = False
    if not retrieved:
        raise CatalogFetchError('not_retrieved')
    current = _validated_url(url)
    deadline = time.monotonic() + TOTAL_TIMEOUT
    try:
        for hop in range(MAX_REDIRECTS + 1):
            parsed = urlsplit(current)
            ip = _resolve_public_ip(parsed.hostname, deadline)
            remaining = _remaining(deadline)
            timeout = urllib3.Timeout(total=remaining, connect=min(CONNECT_TIMEOUT, remaining),
                                      read=min(READ_TIMEOUT, remaining))
            # A numeric host cannot be rebound by DNS between the validation
            # above and connect. Host/SNI/certificate identity remain original.
            with urllib3.HTTPSConnectionPool(ip, port=443, maxsize=1, retries=False,
                    assert_hostname=parsed.hostname, server_hostname=parsed.hostname,
                    cert_reqs=ssl.CERT_REQUIRED, ca_certs=certifi.where()) as pool:
                target = urlunsplit(('', '', parsed.path, parsed.query, ''))
                response = pool.urlopen('GET', target, timeout=timeout, retries=False,
                    redirect=False, preload_content=False, decode_content=False,
                    headers={'Host': parsed.hostname, 'Accept': 'text/html, application/xhtml+xml',
                             'Accept-Encoding': 'identity', 'User-Agent': 'IMC-Mexico-PublicResearch/1.0'})
                try:
                    _remaining(deadline)
                    if response.status in {301, 302, 303, 307, 308}:
                        if hop == MAX_REDIRECTS:
                            raise CatalogFetchError('too_many_redirects')
                        location = response.headers.get('Location')
                        if not location or len(location) > 1600:
                            raise CatalogFetchError('invalid_redirect')
                        if '#' in location or '\\' in location or any(char.isspace() or ord(char) < 32 for char in location):
                            raise CatalogFetchError('unsupported_url')
                        current = _validated_url(urljoin(current, location))
                        continue
                    if response.status != 200:
                        raise CatalogFetchError('http_status')
                    return CatalogPage(html=_read_html(response, deadline), final_url=current)
                finally:
                    response.close()
    except CatalogFetchError:
        raise
    except (urllib3.exceptions.TimeoutError, TimeoutError, socket.timeout):
        raise CatalogFetchError('timeout') from None
    except (urllib3.exceptions.HTTPError, OSError, ValueError, zlib.error):
        raise CatalogFetchError('fetch_failed') from None
    raise CatalogFetchError('too_many_redirects')
