"""Bounded exact/near-duplicate matching against a verified product index.

This module can establish that an uploaded photo is visually the same stock
image as a public catalogue thumbnail. It does not infer a model from shape,
colour, or general machine appearance: a result is returned only when one
thumbnail clears a high pixel-similarity threshold with a clear margin.
"""
from hashlib import sha256
from html.parser import HTMLParser
import io
import re
import ssl
import time
from urllib.parse import urljoin, urlsplit

import certifi
from PIL import Image, ImageChops, ImageOps, ImageStat
import urllib3

from .research import safe_public_url
from .research_catalog import _model_key, _model_tokens
from .research_fetch import CatalogFetchError, _resolve_public_ip
from .research_sources import lookup_brand
from .valuation import _fetch_listing


INDEX_MAX_HTML = 1_000_000
MAX_IMAGES = 12
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MATCH_DEADLINE_SECONDS = 20.0
NORMALIZED_SIZE = (64, 64)
MATCH_THRESHOLD = 0.985
MIN_MARGIN = 0.02
_PRODUCT_PATH = re.compile(r"/product/[^?#]+", re.I)
_MODEL_WORDS = {"develon", "chile", "excavadora", "excavadoras", "sobre", "orugas", "de"}


def _space(value):
    return " ".join(str(value or "").split())


def _canonical_catalog_model(value):
    """Extract a model code from a product label/slug, dropping slug prose."""
    for token in _model_tokens(value):
        parts = token.strip(" ./-").split("-")
        kept = []
        for part in parts:
            if kept and part.casefold() in _MODEL_WORDS:
                break
            if kept and part.casefold() in {"300x300", "367x367", "768x768"}:
                break
            kept.append(part)
        candidate = "-".join(kept).strip(" ./-")
        if candidate and any(char.isdigit() for char in candidate):
            return candidate
    return None


class _ImageIndexParser(HTMLParser):
    """Capture visible product anchors and images exactly as authored."""

    _SKIP = {"script", "style", "template", "nav", "footer", "header", "form", "aside", "noscript"}
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.title_parts = None
        self.title_value = ""
        self.anchor = None
        self.anchors = []
        self.nodes = 0

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        if self.nodes > 30_000:
            raise ValueError("photo_index_node_limit")
        attrs = dict(attrs)
        if self.skip_depth:
            if tag not in self._VOID:
                self.skip_depth += 1
            return
        hidden = (tag in self._SKIP or "hidden" in attrs or attrs.get("aria-hidden") == "true"
                  or "display:none" in attrs.get("style", "").replace(" ", "").lower())
        if hidden:
            if tag not in self._VOID:
                self.skip_depth = 1
            return
        if tag == "title":
            self.title_parts = []
        elif tag == "a":
            self.anchor = {"href": attrs.get("href"), "parts": [], "images": []}
        elif tag == "img" and self.anchor is not None:
            for key in ("src", "data-src", "data-lazy-src"):
                if attrs.get(key):
                    self.anchor["images"].append(attrs[key])
                    break

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag not in self._VOID:
                self.skip_depth = max(0, self.skip_depth - 1)
            return
        if tag == "title" and self.title_parts is not None:
            self.title_value = _space(" ".join(self.title_parts))
            self.title_parts = None
        elif tag == "a" and self.anchor is not None:
            self.anchors.append({**self.anchor,
                                 "text": _space(" ".join(self.anchor["parts"]))})
            self.anchor = None

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.title_parts is not None:
            self.title_parts.append(data)
        if self.anchor is not None:
            self.anchor["parts"].append(data)

    @property
    def title(self):
        return self.title_value


def _parse_index(html):
    parser = _ImageIndexParser()
    try:
        parser.feed(str(html)[:INDEX_MAX_HTML])
        parser.close()
    except (TypeError, ValueError, RecursionError):
        return None
    return parser


def _verified_asset_url(url, domains):
    value = safe_public_url(url)
    if value != url:
        return None
    if urlsplit(value).scheme != "https":
        return None
    host = (urlsplit(value).hostname or "").lower().rstrip(".")
    return value if any(host == domain or host.endswith("." + domain) for domain in domains) else None


def _read_image_response(response, deadline):
    content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        raise CatalogFetchError("not_image")
    if str(response.headers.get("Content-Encoding", "")).strip().lower() not in {"", "identity"}:
        raise CatalogFetchError("unsupported_encoding")
    announced = response.headers.get("Content-Length")
    if announced is not None and (not str(announced).isdigit() or int(announced) > MAX_IMAGE_BYTES):
        raise CatalogFetchError("too_large")
    chunks, size = [], 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CatalogFetchError("timeout")
        chunk = response.read1(min(64 * 1024, MAX_IMAGE_BYTES - size + 1), decode_content=False)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_IMAGE_BYTES:
            raise CatalogFetchError("too_large")
        chunks.append(chunk)
    if not chunks:
        raise CatalogFetchError("empty_body")
    return b"".join(chunks)


def _fetch_image(url, deadline, domains):
    """Fetch one same-host public image with pinned DNS and bounded bytes."""
    current = _verified_asset_url(url, domains)
    if not current:
        raise CatalogFetchError("unsupported_url")
    host_key = (urlsplit(current).hostname or "").lower().rstrip(".")
    for hop in range(3):
        parts = urlsplit(current)
        ip = _resolve_public_ip(parts.hostname, deadline)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CatalogFetchError("timeout")
        with urllib3.HTTPSConnectionPool(ip, port=443, maxsize=1, retries=False,
                assert_hostname=parts.hostname, server_hostname=parts.hostname,
                cert_reqs=ssl.CERT_REQUIRED, ca_certs=certifi.where()) as pool:
            parts_target = urlsplit(current)
            target = parts_target.path or "/"
            if parts_target.query:
                target += "?" + parts_target.query
            response = pool.urlopen(
                "GET", target, timeout=urllib3.Timeout(total=remaining,
                connect=min(3, remaining), read=min(8, remaining)), retries=False,
                redirect=False, preload_content=False, decode_content=False,
                headers={"Host": parts.hostname, "Accept": "image/*", "Accept-Encoding": "identity",
                         "User-Agent": "IMC-Mexico-PublicResearch/1.0"})
            try:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location", "")
                    if hop == 2 or not location:
                        raise CatalogFetchError("invalid_redirect")
                    current = _verified_asset_url(urljoin(current, location), domains)
                    if not current or (urlsplit(current).hostname or "").lower().rstrip(".") != host_key:
                        raise CatalogFetchError("unsupported_redirect")
                    continue
                if response.status != 200:
                    raise CatalogFetchError("http_status")
                return _read_image_response(response, deadline), current
            finally:
                response.close()
    raise CatalogFetchError("too_many_redirects")


def _normalized_image(raw):
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > MAX_IMAGE_BYTES:
        return None
    try:
        image = Image.open(io.BytesIO(raw))
        width, height = image.size
        if (not width or not height or width * height > MAX_IMAGE_PIXELS):
            return None
        image.load()
        if image.mode in {"RGBA", "LA"}:
            base = Image.new("RGB", image.size, "white")
            base.paste(image, mask=image.getchannel("A"))
            image = base
        else:
            image = image.convert("RGB")
        normalized = ImageOps.fit(image, NORMALIZED_SIZE, method=Image.Resampling.BILINEAR)
        if sum(ImageStat.Stat(normalized).var) / 3.0 < 4.0:
            return None
        return normalized
    except (OSError, ValueError, TypeError, Image.DecompressionBombError):
        return None


def _similarity(left, right):
    difference = ImageStat.Stat(ImageChops.difference(left, right))
    return max(0.0, 1.0 - sum(difference.mean) / (3.0 * 255.0))


def match_catalog_photo(photo_bytes, brand, category, *, index_fetcher=None, image_fetcher=None,
                        deadline=None):
    """Return one high-confidence stock-photo catalogue reference, or ``None``.

    ``photo_bytes`` is treated as untrusted local input. The index and image
    fetchers are injectable for tests; production defaults use the bounded
    listing transport plus the pinned image transport above.
    """
    if not isinstance(photo_bytes, (bytes, bytearray)) or len(photo_bytes) > MAX_IMAGE_BYTES:
        return None
    profile = lookup_brand(brand, category)
    domains = tuple(getattr(profile, "catalog_domains", ()) or ()) if profile else ()
    index_urls = tuple(getattr(profile, "catalog_urls", ()) or ()) if profile else ()
    if not profile or profile.brand != "DEVELON" or category != "Excavadoras" or not domains or not index_urls:
        return None
    photo = _normalized_image(photo_bytes)
    if photo is None:
        return None
    deadline = deadline if deadline is not None else time.monotonic() + MATCH_DEADLINE_SECONDS
    index_url = next((_verified_asset_url(url, domains) for url in index_urls
                      if _verified_asset_url(url, domains)), None)
    if not index_url or time.monotonic() >= deadline:
        return None
    index_fetcher = index_fetcher or _fetch_listing
    try:
        page = index_fetcher(index_url, [index_url], deadline)
        html = getattr(page, "html", None)
        final_url = _verified_asset_url(getattr(page, "final_url", index_url), domains)
        if html is None and isinstance(page, (tuple, list)) and len(page) == 2:
            html, returned_url = page
            final_url = _verified_asset_url(returned_url, domains)
    except Exception:
        return None
    if not isinstance(html, str) or not final_url:
        return None
    parser = _parse_index(html)
    if parser is None:
        return None
    products = {}
    for anchor in parser.anchors:
        href = anchor.get("href")
        product_url = _verified_asset_url(urljoin(final_url, href or ""), domains)
        if not product_url or not _PRODUCT_PATH.fullmatch(urlsplit(product_url).path.rstrip("/") + "/"):
            continue
        model = _canonical_catalog_model((anchor.get("text", "") + " " + (href or "")))
        if not model:
            continue
        entry = products.setdefault(product_url, {"models": {}, "images": []})
        entry["models"].setdefault(_model_key(model), model)
        # Prefer a visible card title's casing over a lowercase URL slug.
        visible_model = _canonical_catalog_model(anchor.get("text", ""))
        if visible_model:
            entry["models"][_model_key(visible_model)] = visible_model
        for image in anchor.get("images", ()):
            image_url = _verified_asset_url(urljoin(final_url, image), domains)
            if image_url and image_url not in entry["images"]:
                entry["images"].append(image_url)
    candidates = [item for item in products.values() if item["images"] and len(item["models"]) == 1][:MAX_IMAGES]
    if not candidates:
        return None
    image_fetcher = image_fetcher or (lambda url, end: _fetch_image(url, end, domains))
    scored = []
    fetched_images = 0
    for item in candidates:
        if time.monotonic() >= deadline:
            break
        best = None
        for image_url in item["images"][:2]:
            if fetched_images >= MAX_IMAGES or time.monotonic() >= deadline:
                break
            fetched_images += 1
            try:
                fetched = image_fetcher(image_url, deadline)
                raw, final_image_url = fetched if isinstance(fetched, tuple) else (fetched, image_url)
                thumb = _normalized_image(raw)
                if thumb is None:
                    continue
                score = _similarity(photo, thumb)
                if best is None or score > best[0]:
                    best = (score, final_image_url, sha256(raw).hexdigest())
            except Exception:
                continue
        if best is not None:
            item["model"] = next(iter(item["models"].values()))
            scored.append((best[0], item, best[1], best[2]))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < MATCH_THRESHOLD:
        return None
    best = scored[0]
    runner_up = next((item for item in scored[1:] if item[1]["model"] != best[1]["model"]), None)
    if runner_up is not None and best[0] - runner_up[0] < MIN_MARGIN:
        return None
    return {
        "model": best[1]["model"], "source_url": next(url for url, value in products.items() if value is best[1]),
        "image_url": best[2], "score": round(best[0], 6), "photo_sha256": sha256(photo_bytes).hexdigest(),
        "image_sha256": best[3], "source_title": parser.title[:200],
        "origin": "direct_verified_catalog_photo_match",
    }
