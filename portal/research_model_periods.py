"""Typed LECTURA catalogue metadata, never a quotation of a fetched page body.

Only the catalogue's exact model-page URL and standard retrieved title may
supply these model periods. This module performs no I/O. Its result is signed
by the ordinary research manifest together with the actual retrieved sources.
"""
from copy import deepcopy
import re
from urllib.parse import urlsplit

from django.utils import timezone


PERIOD_ORIGIN = 'lectura_catalogue_metadata_v1'
PERIOD_KEYS = ('estimated_year_from', 'estimated_year_to', 'estimated_year_basis')
MAX_PERIOD_RECORDS = 4
_TITLE = re.compile(
    r'(?P<identity>[^\r\n]{1,120}) (?:Specifications & Technical Data|excavator specs & dimensions) '
    r'\((?P<start>\d{4})\s*[-–—]\s*(?P<end>\d{4})\) \| LECTURA Specs')
_PATH = re.compile(r'/en/model/(?:[a-z0-9]+(?:-[a-z0-9]+)*/){1,5}'
                   r'(?P<model>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<id>[1-9]\d*)')


def _record(source, identity):
    from .research import _brand_aliases, identifier_key, safe_public_url

    if not isinstance(source, dict) or not isinstance(identity, dict):
        return None
    brand, model = identity.get('brand'), identity.get('model')
    if not isinstance(brand, str) or not isinstance(model, str) or not brand or not model:
        return None
    url, title = source.get('url'), source.get('title')
    if not isinstance(title, str) or len(title) > 200 or safe_public_url(url) != url:
        return None
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.netloc != 'www.lectura-specs.com' or parts.fragment
            or parts.query not in {'', 'utm_source=openai', 'utm_source=chatgpt.com'}):
        return None
    path, match = _PATH.fullmatch(parts.path), _TITLE.fullmatch(title)
    if not path or not match or identifier_key(path['model']) != identifier_key(model):
        return None
    # Exact identity segment: a shared/variant title cannot lend its dates to
    # the base model. No arbitrary prose or date elsewhere in a title counts.
    aliases = _brand_aliases(brand)
    identity_ok = any(re.fullmatch(re.escape(alias) + r'\s+(.+)', match['identity'], re.I)
                      and identifier_key(re.fullmatch(re.escape(alias) + r'\s+(.+)',
                          match['identity'], re.I).group(1)) == identifier_key(model)
                      for alias in aliases)
    parent_slug = parts.path.split('/')[-2]
    brand_path_ok = any(parent_slug.endswith('-' + re.sub(r'\s+', '-', alias.casefold()))
                        for alias in aliases)
    if not identity_ok or not brand_path_ok:
        return None
    start, end = int(match['start']), int(match['end'])
    if not 1900 <= start <= end <= timezone.now().year:
        return None
    return {'source_url': url, 'source_title': title,
            'start_year': str(start), 'end_year': str(end)}


def _fields(records, source_date):
    if not records or len(records) > MAX_PERIOD_RECORDS:
        return []
    records = sorted(records, key=lambda item: (int(item['start_year']), int(item['end_year']), item['source_url']))
    start, end = int(records[0]['start_year']), int(records[0]['end_year'])
    for record in records[1:]:
        if int(record['start_year']) > end + 1:
            return []  # Missing catalogue years must not become implied coverage.
        end = max(end, int(record['end_year']))
    periods = list(dict.fromkeys(f"{record['start_year']}–{record['end_year']}" for record in records))
    basis = ('Periodos catalogados por LECTURA: ' + ', '.join(periods) +
             f'. Referencia amplia del modelo: {start}–{end}; año de esta unidad por confirmar.')
    evidence = 'Metadatos de catálogo LECTURA (títulos recuperados): ' + ' | '.join(
        record['source_title'] for record in records)
    if len(evidence) > 800 or len(basis) > 300:
        return []
    common = {'scope': 'model', 'source_url': records[0]['source_url'],
              'source_title': records[0]['source_title'], 'source_date': source_date,
              'evidence': evidence, 'authority_validated': False, 'matched_serial': None,
              'period_origin': PERIOD_ORIGIN, 'period_records': records}
    return [{**deepcopy(common), 'key': key, 'value': value} for key, value in zip(
        PERIOD_KEYS, (str(start), str(end), basis))]


def lectura_catalogue_period_fields(identity, sources, source_titles, *, source_date=None):
    """Derive a bounded range only from matching tool-retrieved source metadata.

    source_titles is the server's retrieval map, never model candidate text.
    A duplicate catalogue URL with contradictory titles vetoes the adapter.
    """
    from .research import _retrieved_url_identity, safe_public_url

    if not isinstance(source_titles, dict):
        return []
    records, seen = [], {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = source.get('url')
        if not safe_public_url(url):
            continue
        canonical = _retrieved_url_identity(url)
        title = source.get('title')
        if canonical in seen and seen[canonical] != title:
            return []
        seen[canonical] = title
        if not isinstance(title, str) or source_titles.get(url) != title:
            continue
        record = _record(source, identity)
        if record and not any(_retrieved_url_identity(item['source_url']) == canonical for item in records):
            records.append(record)
    return _fields(records, source_date or timezone.localdate().isoformat())


def validated_catalogue_period_fields(research):
    """Recompute typed semantics; the caller must also verify the manifest HMAC."""
    if not isinstance(research, dict):
        return {}
    fields = [field for field in research.get('fields', [])
              if isinstance(field, dict) and field.get('key') in PERIOD_KEYS]
    if len(fields) != 3 or {field['key'] for field in fields} != set(PERIOD_KEYS):
        return {}
    first = fields[0]
    records = first.get('period_records')
    if (first.get('period_origin') != PERIOD_ORIGIN or not isinstance(records, list)
            or not 1 <= len(records) <= MAX_PERIOD_RECORDS):
        return {}
    sources = research.get('sources', [])
    if not isinstance(sources, list):
        return {}
    source_map = {source.get('url'): source.get('title') for source in sources if isinstance(source, dict)}
    titles = {}
    for record in records:
        if (not isinstance(record, dict) or set(record) != {'source_url', 'source_title', 'start_year', 'end_year'}
                or source_map.get(record.get('source_url')) != record.get('source_title')):
            return {}
        titles[record['source_url']] = record['source_title']
    expected = lectura_catalogue_period_fields(research.get('identity'), sources, titles,
                                               source_date=first.get('source_date'))
    if len(expected) != 3:
        return {}
    by_key = {field['key']: field for field in fields}
    if any(any(by_key[item['key']].get(key) != value for key, value in item.items()) for item in expected):
        return {}
    return by_key
