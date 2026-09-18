"""Read a small number of retrieved public specification tables, without AI."""
from urllib.parse import urlsplit

from .research import (
    MAX_CITED_PASSAGES, MAX_RESEARCH_SOURCES, _contains_identifier,
    _retrieved_url_identity, _source_title_context,
)
from .research_fetch import CatalogFetchError, fetch_catalog_html, supports_catalog_url
from .research_catalogs import parse_catalog_html


def collect_registered_fields(identity, category, sources, passages, titles, allowed=None):
    """Read a registered regional catalogue for an already identified model.

    Literal rows enter the same signed evidence validator as retrieved manuals.
    An index never supplies the unit's identity, location or year.
    """
    from .research_catalog import catalog_product_fields
    from .research_sources import lookup_brand
    from .valuation import _fetch_listing
    profile = lookup_brand(identity.get('brand'), category)
    if not identity.get('model') or not profile or not profile.catalog_urls:
        return [], [], False
    if allowed is not None and not allowed():
        return [], [], True
    attempt = {'host': urlsplit(profile.catalog_urls[0]).hostname, 'status': 'no_data',
               'origin': 'registered_regional_catalog'}
    try:
        document = catalog_product_fields({**identity, 'brand': profile.brand, 'category': category},
                                          fetcher=_fetch_listing)
    except Exception:
        attempt.update(status='unavailable', reason='document_parse_failed')
        return [], [attempt], False
    if allowed is not None and not allowed():
        return [], [attempt], True
    if not document:
        return [], [attempt], False
    url, title = document['source_url'], document['source_title']
    sources.append({'url': url, 'title': title})
    titles[url] = title
    fields = document['fields'][:10]
    for field in fields:
        entry = {'passage_index': len(passages), 'source_url': url, 'source_title': title,
                 'text': field.evidence, 'origin': 'direct_document'}
        if _source_title_context(title, identity, field.evidence):
            entry['identity_context'] = {'origin': 'same_source_title', 'title': title}
        passages.append(entry)
    attempt.update(status='evidence_found', parsed_field_count=len(fields), retained_field_count=len(fields))
    return fields, [attempt], False


def collect_document_fields(identity, retrieved, sources, passages, titles, allowed=None):
    """Append literal document evidence, bounded to two pages and twenty fields.

    Search-result URLs authorize retrieval, never the facts. The parser checks
    the actual document heading and rows; normalize_research checks them again.
    """
    if not identity.get("brand") or not identity.get("model"):
        return [], [], False
    candidates, seen = [], set()
    for source in retrieved[:MAX_RESEARCH_SOURCES]:
        url = source["url"]
        canonical = _retrieved_url_identity(url)
        if canonical not in seen and supports_catalog_url(url):
            seen.add(canonical)
            candidates.append(source)
    candidates.sort(key=lambda s: (not _contains_identifier(s.get("title", ""), identity.get("serial")),
                                   not _contains_identifier(s.get("title", ""), identity["model"])))
    # Give an independent catalog a chance after a manufacturer result.
    selected, hosts = [], set()
    for source in candidates:
        host = urlsplit(source["url"]).hostname
        if host not in hosts:
            selected.append(source)
            hosts.add(host)
    selected.extend(s for s in candidates if s not in selected)
    fields, attempts = [], []
    for source in selected[:2]:
        if allowed is not None and not allowed():
            return [], attempts, True
        attempt = {"host": urlsplit(source["url"]).hostname, "status": "no_data"}
        attempts.append(attempt)
        try:
            page = fetch_catalog_html(source["url"], retrieved_urls=[s["url"] for s in retrieved])
            if allowed is not None and not allowed():
                return [], attempts, True
            document = parse_catalog_html(page.html, page.final_url, identity)
            attempt["status"] = document["status"]
            attempt["parsed_field_count"] = len(document["fields"])
        except CatalogFetchError as exc:
            attempt.update(status="unavailable", reason=exc.code)
            continue
        except Exception:
            # A layout change cannot break the photo/search workflow. Do not
            # include server responses or identifiers in diagnostics.
            attempt.update(status="unavailable", reason="document_parse_failed")
            continue
        if not document["fields"]:
            continue
        url, title = page.final_url, document["title"]
        # Reserve space for literal table rows, without dropping an earlier
        # direct document. Model normalization happens after this reindexing.
        web = [p for p in passages if p.get("origin") != "direct_document"][:16]
        direct = [p for p in passages if p.get("origin") == "direct_document"]
        while web and sum(len(p["text"]) for p in web + direct) > 12000:
            web.pop()
        passages[:] = web + direct
        if url not in {s["url"] for s in sources}:
            if len(sources) >= MAX_RESEARCH_SOURCES:
                retained_urls = {p["source_url"] for p in passages}
                unused = next((s for s in sources if s["url"] not in retained_urls), None)
                if unused is None:
                    continue
                sources.remove(unused)
            sources.append({"url": url, "title": title})
        else:
            next(s for s in sources if s["url"] == url)["title"] = title
        titles[url] = title
        for field in document["fields"][:10]:
            if len(passages) >= MAX_CITED_PASSAGES or len(fields) >= 20:
                break
            text = field.evidence
            if not text or len(text) > 650 or sum(len(p["text"]) for p in passages) + len(text) > 18000:
                continue
            entry = {"source_url": url, "source_title": title, "text": text, "origin": "direct_document"}
            if _source_title_context(title, identity, text):
                entry["identity_context"] = {"origin": "same_source_title", "title": title}
            passages.append(entry)
            fields.append(field)
        for index, passage in enumerate(passages):
            passage["passage_index"] = index
        attempt["retained_field_count"] = sum(f.source_url == url for f in fields)
    return fields, attempts, False
