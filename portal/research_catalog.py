"""Bounded direct reads of verified manufacturer catalogue index pages.

This fallback is intentionally narrower than ordinary web research. It reads
only a registry URL selected for a known brand/category, never accepts a URL
from the photographed machine or a search result, and returns model leads as
unconfirmed catalogue references. The caller still owns consent, signing and
the decision to present or merge a hypothesis.
"""
from html.parser import HTMLParser
import re
import time
from urllib.parse import urljoin, urlsplit

from django.utils import timezone

from .research import safe_public_url
from .research_sources import lookup_brand


MAX_PAGES = 1
MAX_CANDIDATES = 8
MAX_HTML_CHARS = 1_000_000
CATALOG_DEADLINE_SECONDS = 14.0
_IGNORED = {"script", "style", "template", "nav", "footer", "header", "form", "aside", "noscript"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_MODEL = re.compile(
    r"(?<![A-Za-z0-9])(?P<model>(?:[A-Za-z]{1,10}\d[A-Za-z0-9./-]{1,30}|\d+[A-Za-z][A-Za-z0-9./-]{1,30}))(?![A-Za-z0-9])"
)
_PRODUCT_PATH = re.compile(r"/(?:products?|construction-equipment|equipment|machines)(?:/|$)", re.I)
_REGIONAL_PRODUCT_PATH = re.compile(r"/product/[^?#]+", re.I)
_DEVELON_MODEL = re.compile(r"(?<![A-Za-z0-9])DX\s*\d+[A-Za-z0-9./-]*(?![A-Za-z0-9])", re.I)


def _model_key(value):
    return "".join(char.casefold() for char in str(value or "") if char.isalnum())


def _model_tokens(value):
    return [match.group(0).strip(" ./-") for match in _DEVELON_MODEL.finditer(str(value or ""))]


def _space(value):
    return " ".join(str(value or "").split())


class _CatalogueParser(HTMLParser):
    """Keep only visible product headings and anchors from untrusted HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.hidden_depth = 0
        self.title_parts, self.title_value = None, ""
        self.heading_parts, self.anchor_parts = [], []
        self.headings, self.anchors = [], []
        self.product_headings = []
        self.anchor_href = None
        self.nodes = 0

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        if self.nodes > 20000:
            raise ValueError("catalogue_node_limit")
        attrs = dict(attrs)
        if tag in _VOID:
            return
        hidden = (tag in _IGNORED or "hidden" in attrs or attrs.get("aria-hidden") == "true"
                  or "display:none" in attrs.get("style", "").replace(" ", "").lower())
        product = "list__headline" in attrs.get("class", "").split()
        self.stack.append((tag, hidden, product))
        if hidden:
            self.hidden_depth += 1
        if tag == "title":
            self.title_parts = []
        if tag in {"h1", "h2", "h3"} and not self.hidden_depth:
            self.heading_parts.append(([], tag == "h2" and any(node[2] for node in self.stack)))
        if tag == "a" and not self.hidden_depth:
            self.anchor_parts.append([])
            self.anchor_href = attrs.get("href")

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            current, hidden, _ = self.stack[index]
            if current != tag:
                continue
            self.hidden_depth = max(0, self.hidden_depth - sum(node[1] for node in self.stack[index:]))
            del self.stack[index:]
            if tag == "title" and self.title_parts is not None:
                self.title_value = _space(" ".join(self.title_parts))
                self.title_parts = None
            if tag in {"h1", "h2", "h3"} and self.heading_parts:
                parts, product = self.heading_parts.pop()
                value = _space(" ".join(parts))
                if value:
                    self.headings.append(value)
                    if product:
                        self.product_headings.append(value)
            if tag == "a" and self.anchor_parts:
                value = _space(" ".join(self.anchor_parts.pop()))
                if value:
                    self.anchors.append((value, self.anchor_href))
                self.anchor_href = None
            return

    def handle_data(self, data):
        if self.hidden_depth:
            return
        if self.title_parts is not None:
            self.title_parts.append(data)
        if self.heading_parts:
            self.heading_parts[-1][0].append(data)
        if self.anchor_parts:
            self.anchor_parts[-1].append(data)

    @property
    def title(self):
        return self.title_value


def _category_url(profile, category):
    """Select only a general category entry point from the verified registry."""
    if category != "Excavadoras":
        return None
    for url in profile.documentation_urls:
        parts = urlsplit(url)
        if (parts.path.rstrip("/").casefold().endswith("/products/crawler-excavators")
                and not re.search(r"/dx\d", parts.path, re.I)):
            return url
    return None


def _verified_url(url, domains):
    value = safe_public_url(url)
    if value != url:
        return None
    host = (urlsplit(value).hostname or "").lower().rstrip(".")
    if not any(host == domain or host.endswith("." + domain) for domain in domains):
        return None
    return value


def _candidate_model(text):
    models = []
    for match in _MODEL.finditer(text):
        value = _space(match.group("model")).strip("./-")
        if (not value or value.isdigit() or len(value) < 3
                or value.casefold() in {"html", "http", "https"}
                or not any(char.isalpha() for char in value)):
            continue
        if value.casefold() not in {item.casefold() for item in models}:
            models.append(value)
    return models


def _whole_model(text):
    """Read one complete product heading, including spaced suffixes."""
    value = _space(text)
    if (not value or len(value) > 80 or not re.fullmatch(r"DX\d+[A-Za-z0-9 ./-]*", value, re.I)
            or not any(char.isalpha() for char in value)
            or not any(char.isdigit() for char in value)):
        return None
    return value


def _fetch_page(fetcher, url, deadline):
    result = fetcher(url, [url], deadline)
    html = getattr(result, "html", None)
    final_url = getattr(result, "final_url", None)
    if html is None and isinstance(result, (tuple, list)) and len(result) == 2:
        html, final_url = result
    if not isinstance(html, str) or not isinstance(final_url, str):
        return None
    return html[:MAX_HTML_CHARS], final_url


def catalog_listing_candidates(identity, category, *, fetcher=None, deadline=None):
    """Read verified manufacturer catalogue headings into unconfirmed leads.

    ``fetcher`` is normally ``valuation._fetch_listing`` and is injectable for
    tests. It must perform pinned HTTPS, public-DNS, same-host redirect checks;
    this function does not weaken those checks. Only one registry entry point
    is requested; failure falls back to the ordinary research pipeline.
    """
    if not isinstance(identity, dict) or identity.get("model"):
        return []
    brand, category = identity.get("brand"), category or identity.get("category")
    profile = lookup_brand(brand, category)
    if profile is None:
        return []
    entry = _category_url(profile, category)
    if not entry or fetcher is None:
        return []
    entry = _verified_url(entry, profile.manufacturer_domains)
    if not entry:
        return []
    if deadline is None:
        deadline = time.monotonic() + CATALOG_DEADLINE_SECONDS
    if time.monotonic() >= deadline:
        return []
    pages = []
    try:
        fetched = _fetch_page(fetcher, entry, min(deadline, time.monotonic() + CATALOG_DEADLINE_SECONDS))
        if fetched is None:
            return []
        html, final_url = fetched
        final_url = _verified_url(final_url, profile.manufacturer_domains)
        if not final_url:
            return []
        pages.append((html, final_url))
    except Exception:
        return []
    leads, seen = [], set()
    for html, source_url in pages[:MAX_PAGES]:
        if time.monotonic() >= deadline:
            break
        parser = _CatalogueParser()
        try:
            parser.feed(html)
            parser.close()
        except (ValueError, TypeError, RecursionError):
            continue
        title = parser.title
        if (not title or not re.search(r"\bdevelon\b", title, re.I)
                or not any(re.search(r"\bcrawler\s+excavator", heading, re.I)
                           for heading in parser.headings)):
            continue
        anchor_by_model = {}
        for anchor_text, href in parser.anchors:
            anchor_url = _verified_url(urljoin(source_url, href or ""), profile.manufacturer_domains)
            if not anchor_url or not _PRODUCT_PATH.search(urlsplit(anchor_url).path):
                continue
            for model in _candidate_model(anchor_text + " " + (href or "")):
                anchor_by_model.setdefault(model.casefold().replace("-", "").replace(" ", ""), anchor_url)
        for heading in parser.product_headings:
            model = _whole_model(heading)
            if not model:
                continue
            key = model.casefold().replace("-", "").replace(" ", "")
            if key in seen:
                continue
            seen.add(key)
            leads.append({
                "model": model, "status": "hypothesis", "confidence": "lead",
                "support_count": 1, "source_url": source_url, "source_title": title[:200],
                "source_date": timezone.localdate().isoformat(),
                "evidence": f"{title[:120]}. Catálogo de productos: {heading[:500]}",
                "supporting_sources": [{"url": source_url, "title": title[:200]}],
                "anchor_url": anchor_by_model.get(key, source_url), "origin": "direct_manufacturer_catalog",
            })
            if len(leads) >= MAX_CANDIDATES:
                return leads
    return leads


class _RegionalProductParser(HTMLParser):
    """Small visible-text parser for the verified Chile WooCommerce pages."""

    _SKIP = {"script", "style", "template", "nav", "footer", "header", "form", "aside", "noscript"}
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.title_parts = None
        self.title_value = ""
        self.heading = []
        self.headings = []
        self.anchor = None
        self.anchors = []
        self.row = None
        self.cell = None
        self.rows = []
        self.nodes = 0

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        if self.nodes > 25000:
            raise ValueError("regional_catalog_node_limit")
        attrs = dict(attrs)
        if self.skip_depth:
            if tag not in self._VOID:
                self.skip_depth += 1
            return
        hidden = (tag in self._SKIP or "hidden" in attrs or attrs.get("aria-hidden") == "true"
                  or "display:none" in attrs.get("style", "").replace(" ", "").lower())
        if hidden:
            if tag in self._VOID:
                return
            self.skip_depth = 1
            return
        if tag == "title":
            self.title_parts = []
        elif tag in {"h1", "h2", "h3", "h4"}:
            self.heading.append([])
        elif tag == "a":
            self.anchor = {"parts": [], "href": attrs.get("href")}
        elif tag == "tr":
            self.row = []
        elif tag in {"th", "td"} and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag not in self._VOID:
                self.skip_depth = max(0, self.skip_depth - 1)
            return
        if tag == "title" and self.title_parts is not None:
            self.title_value = _space(" ".join(self.title_parts))
            self.title_parts = None
        elif tag in {"h1", "h2", "h3", "h4"} and self.heading:
            value = _space(" ".join(self.heading.pop()))
            if value:
                self.headings.append(value)
        elif tag == "a" and self.anchor is not None:
            text = _space(" ".join(self.anchor["parts"]))
            self.anchors.append((text, self.anchor.get("href")))
            self.anchor = None
        elif tag in {"th", "td"} and self.cell is not None:
            if self.row is not None:
                self.row.append(_space(" ".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if len(self.row) >= 2:
                self.rows.append(tuple(self.row[:2]))
            self.row = None

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.title_parts is not None:
            self.title_parts.append(data)
        if self.heading:
            self.heading[-1].append(data)
        if self.anchor is not None:
            self.anchor["parts"].append(data)
        if self.cell is not None:
            self.cell.append(data)

    @property
    def title(self):
        return self.title_value


def _regional_entry(profile, category):
    if category != "Excavadoras":
        return None
    domains = tuple(getattr(profile, "catalog_domains", ()) or ())
    urls = tuple(getattr(profile, "catalog_urls", ()) or ())
    for value in urls:
        verified = _verified_url(value, domains)
        if verified and urlsplit(verified).path.rstrip("/").casefold().endswith(
                "/product-category/excavadoras-sobre-orugas"):
            return verified
    return None


def _parse_regional(html):
    parser = _RegionalProductParser()
    try:
        parser.feed(html[:MAX_HTML_CHARS])
        parser.close()
    except (ValueError, TypeError, RecursionError):
        return None
    return parser


def _regional_fetch(fetcher, url, deadline, domains):
    if time.monotonic() >= deadline:
        return None
    try:
        fetched = _fetch_page(fetcher, url, deadline)
    except Exception:
        return None
    if fetched is None:
        return None
    html, final_url = fetched
    final_url = _verified_url(final_url, domains)
    return (html, final_url) if final_url else None


def _regional_row_fields(parser, source_url, source_title, model):
    """Map only literal technical rows; unknown labels remain unclaimed."""
    from .research import ResearchField
    labels = {
        "peso operativo": "weight", "capacidad del balde": "capacity",
        "potencia del motor": "power", "motor": "engine",
        "combustible": "fuel", "dimensiones": "dimensions",
        "profundidad máxima de excavación": "digging_depth",
        "sistema hidráulico": "hydraulic_system",
    }
    fields = []
    for label, value in parser.rows:
        key = labels.get(" ".join(label.casefold().split()))
        value = _space(value)
        if not key or not value or len(value) > 300:
            continue
        # Bind the literal row to the page's primary title. This lets the
        # normalizer establish model scope from same-source metadata while
        # retaining the exact table label and value.
        evidence = f"{source_title}: {label}: {value}"
        fields.append(ResearchField(key=key, value=value, scope="model",
                                    source_url=source_url, evidence=evidence,
                                    matched_serial=None, matched_brand="DEVELON",
                                    matched_model=model))
    return fields


def catalog_product_fields(identity, model_hint=None, *, fetcher=None, deadline=None):
    """Read one verified DEVELON Chile product page for a clear model token.

    The regional index is authoritative only for discovering a same-domain
    product URL. ``model_hint`` must come from a separate literal observation
    (normally OCR or a user declaration); this function never chooses a model
    from the index and never compares catalogue thumbnails.
    """
    if not isinstance(identity, dict) or fetcher is None:
        return None
    if identity.get("brand") != "DEVELON" or identity.get("category") != "Excavadoras":
        return None
    hint = model_hint or identity.get("model")
    hint_tokens = _model_tokens(hint)
    if len(hint_tokens) != 1:
        return None
    hint = hint_tokens[0]
    profile = lookup_brand(identity.get("brand"), identity.get("category"))
    if profile is None:
        return None
    entry = _regional_entry(profile, identity.get("category"))
    domains = tuple(getattr(profile, "catalog_domains", ()) or ())
    if not entry or not domains:
        return None
    deadline = deadline if deadline is not None else time.monotonic() + CATALOG_DEADLINE_SECONDS
    category_page = _regional_fetch(fetcher, entry, deadline, domains)
    if category_page is None:
        return None
    category_html, category_url = category_page
    category_parser = _parse_regional(category_html)
    if category_parser is None or not any("excav" in heading.casefold() for heading in category_parser.headings):
        return None
    candidates = {}
    for text, href in category_parser.anchors:
        if not href:
            continue
        url = _verified_url(urljoin(category_url, href), domains)
        if not url or not _REGIONAL_PRODUCT_PATH.fullmatch(urlsplit(url).path.rstrip("/") + "/"):
            continue
        if any(_model_key(token) == _model_key(hint) for token in _model_tokens(text + " " + href)):
            candidates[url] = True
    if len(candidates) != 1 or time.monotonic() >= deadline:
        return None
    product_url = next(iter(candidates))
    product_page = _regional_fetch(fetcher, product_url, deadline, domains)
    if product_page is None:
        return None
    product_html, final_product_url = product_page
    product_parser = _parse_regional(product_html)
    if product_parser is None:
        return None
    # The document title is the primary product identity. Searching every
    # heading would let a Related Products card for another model validate a
    # page whose main product is different.
    page_models = _model_tokens(product_parser.title)
    if (not page_models or any(_model_key(token) != _model_key(hint) for token in page_models)
            or not re.search(r"\bdevelon\b", product_parser.title, re.I)):
        return None
    page_model = page_models[0]
    fields = _regional_row_fields(product_parser, final_product_url, product_parser.title, page_model)
    if not fields:
        return None
    return {
        "model": page_model,
        "source_url": final_product_url,
        "source_title": product_parser.title[:200],
        "source_date": timezone.localdate().isoformat(),
        "fields": fields,
        "evidence": f"{product_parser.title[:160]}; ficha técnica visible en la página del producto.",
        "origin": "direct_verified_regional_catalog",
    }
