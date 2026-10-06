#!/usr/bin/env python3
"""Collect cited metric specifications from public Komatsu product pages.

This is intentionally a bounded current-product collector. It gets the exact
model title and URL from Komatsu's public product navigation, then retains only
metric measurements visibly labelled on the matching product page.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import html
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://www.komatsu.com"
INDEX = BASE + "/en-us/products"
HEADERS = {"User-Agent": "IMC-Mexico-catalogue-research/1.0 (public product specifications)"}


def fetch(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def category_for(path):
    if "/dozers/" in path:
        return "tractores", "tractor sobre orugas"
    if "/excavators/" in path:
        return "excavadoras", "excavadora hidráulica"
    if "/motor-graders/" in path:
        return "motoniveladoras", "motoniveladora"
    if "/trucks/" in path:
        return "camiones", "camión fuera de carretera"
    if "/backhoe-loaders/" in path:
        return "retroexcavadoras", "retroexcavadora"
    if any(item in path for item in ("/wheel-loaders/", "/small-articulated-loaders/")):
        return "cargadores", "cargador sobre ruedas"
    if any(item in path for item in ("/compact-track-loaders/", "/skid-steer-loaders/", "/mini-track-loaders/")):
        return "minicargadores", "minicargador"
    return None


def product_nodes(index_html):
    match = re.search(r"data-menu='([^']+)'", index_html, re.S)
    if not match:
        raise ValueError("Komatsu product navigation was not found")
    tree = json.loads(html.unescape(match.group(1)))
    nodes = []

    def walk(node):
        path = node.get("path", "")
        category = category_for(path)
        if category and not node.get("children") and node.get("title"):
            nodes.append((node["title"].strip(), path, category))
        for child in node.get("children", []):
            walk(child)

    for node in tree:
        walk(node)
    return sorted({(name, path, category) for name, path, category in nodes}, key=lambda item: item[1])


class MetricSpecs(HTMLParser):
    """Extract each labelled metric value from the product's specs component."""
    def __init__(self):
        super().__init__()
        self.metric = False
        self.span_depth = 0
        self.current = []
        self.spans = []
        self.pairs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li" and attrs.get("data-unit") == "METRIC":
            self.metric = True
            self.spans = []
        if self.metric and tag == "span":
            self.span_depth += 1
            self.current = []

    def handle_data(self, data):
        if self.metric and self.span_depth:
            self.current.append(data)

    def handle_endtag(self, tag):
        if self.metric and tag == "span" and self.span_depth:
            self.span_depth -= 1
            if self.span_depth == 0:
                value = " ".join("".join(self.current).split())
                if value:
                    self.spans.append(value)
        if tag == "li" and self.metric:
            if len(self.spans) >= 2:
                self.pairs.append((self.spans[0], self.spans[1]))
            self.metric = False


def specs_from_html(page_html, model):
    parser = MetricSpecs()
    parser.feed(page_html)
    labels = {label.casefold(): (label, value) for label, value in parser.pairs}
    selected = {}
    def take(key, patterns):
        for normalized_label, (label, value) in labels.items():
            if any(pattern in normalized_label for pattern in patterns):
                unit = "kW" if normalized_label.endswith("(kw)") else "kg" if normalized_label.endswith("(kg)") else "mm" if normalized_label.endswith("(mm)") else "kph" if normalized_label.endswith("(kph)") else ""
                rendered = value if re.search(r"\b(?:kw|kg|mm|kph|m3|m³)\b", value, re.I) else f"{value} {unit}".strip()
                selected[key] = {"value": rendered, "evidence": f"Komatsu {model}: {label} {value}."}
                return
    take("engine", ("engine model",))
    take("power", ("net (kw)", "gross (kw)", "horsepower (kw)"))
    take("weight", ("operating weight (kg)",))
    # A current HD605-10 page labels a payload value of "64.1" as kg.  The
    # displayed number is therefore not a usable, unit-safe capacity fact and
    # must not be guessed as tonnes or cubic metres.
    take("digging_depth", ("maximum digging depth (mm)",))
    take("travel_speed", ("maximum travel speed (kph)",))
    return selected


def record(node, retrieved_at):
    model, path, (category_slug, type_es) = node
    source = BASE + path
    try:
        specs = specs_from_html(fetch(source), model)
    except Exception as exc:  # one unavailable product must not corrupt a release
        return source, None, type(exc).__name__
    if not specs:
        return source, None, "no_supported_metric_specs"
    return source, {
        "category_slug": category_slug, "brand": "Komatsu", "model": model,
        "variant": "", "generation": "", "market": "US", "source": source,
        "source_title": f"{model} | Komatsu", "source_version": "US public product page",
        "retrieved_at": retrieved_at,
        "provenance": {"authority": "manufacturer", "scope": "model", "type_es": type_es,
                       "type_en": "construction equipment", "market_scope": "US current product page",
                       "note": "Valores métricos publicados para la configuración de página del fabricante; no acreditan opciones ni condición de una unidad concreta."},
        "specs": specs,
    }, None


def normalized_sources(paths):
    """Read public source URLs already represented by an approved release."""
    sources = set()
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        for reference in document.get("references", []):
            source = reference.get("source") if isinstance(reference, dict) else None
            if isinstance(source, str) and source.startswith("https://"):
                sources.add(source.casefold())
    return sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retrieved-at", default=dt.date.today().isoformat())
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int, help="Process only the first N deterministic product URLs.")
    parser.add_argument("--offset", type=int, default=0, help="Skip N deterministic product URLs before --limit.")
    parser.add_argument("--exclude-source-file", type=Path, action="append", default=[],
                        help="Approved JSON release whose case-normalized source URLs must not be duplicated.")
    args = parser.parse_args()
    nodes = product_nodes(fetch(INDEX))
    nodes = nodes[max(0, args.offset):]
    if args.limit is not None:
        nodes = nodes[:max(0, args.limit)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 3))) as pool:
        outcomes = list(pool.map(lambda node: record(node, args.retrieved_at), nodes))
    existing_sources = normalized_sources(args.exclude_source_file)
    raw_references = [item for _, item, error in outcomes if item]
    references = sorted((item for item in raw_references if item["source"].casefold() not in existing_sources),
                        key=lambda item: item["source"])
    document = {"schema_version": 1, "source": {"provider": "Komatsu", "index": INDEX,
                "retrieved_at": args.retrieved_at, "candidate_product_count": len(nodes),
                "references_with_supported_metric_specs": len(references),
                "unavailable_or_unsupported_pages": sum(item is None for _, item, _ in outcomes),
                "excluded_exact_duplicate_with_existing_bundle": len(raw_references) - len(references)},
                "references": references}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(references)} cited Komatsu records from {len(nodes)} product pages")


if __name__ == "__main__":
    main()
