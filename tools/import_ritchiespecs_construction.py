#!/usr/bin/env python3
"""Build a factual construction-model identity index from RitchieSpecs' public sitemap.

The sitemap is an explicitly public discovery surface. This tool stores only
the model identity encoded by each sitemap URL. It never manufactures a
technical specification from a model name.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

SITEMAP_URL = "https://www.ritchiespecs.com/sitemap.xml"
USER_AGENT = "IMC-Mexico-catalogue-research/1.0 (public sitemap index)"

# Exact family slugs advertised below /industry/construction on 2026-10-06.
# Value is (existing IMC category slug, Spanish family label).
CONSTRUCTION_TYPES = {
    "articulated-dump-truck": ("camiones", "camión articulado"),
    "compactor": ("compactadores", "compactador"),
    "crawler-loader": ("cargadores", "cargador sobre orugas"),
    "crawler-pipe-layer": ("tiendetubos", "tiendetubos sobre orugas"),
    "crawler-tractor": ("tractores", "tractor sobre orugas"),
    "elevating-motor-scraper": ("mototraillas", "mototraílla elevadora"),
    "hydraulic-excavator": ("excavadoras", "excavadora hidráulica"),
    "integrated-tool-carrier": ("cargadores", "cargador portaherramientas integrado"),
    "loader-backhoe": ("retroexcavadoras", "retroexcavadora"),
    "midi-excavator": ("excavadoras", "excavadora midi"),
    "mini-excavator": ("excavadoras", "miniexcavadora"),
    "mobile-excavator": ("excavadoras", "excavadora móvil"),
    "motor-grader": ("motoniveladoras", "motoniveladora"),
    "motor-scraper": ("mototraillas", "mototraílla"),
    "multi-terrain-loader": ("minicargadores", "cargador multiterreno"),
    "rock-truck": ("camiones", "camión rígido fuera de carretera"),
    "shovel": ("excavadoras", "pala mecánica"),
    "skid-steer-loader": ("minicargadores", "minicargador"),
    "wheel-dozer": ("tractores", "tractor sobre ruedas"),
    "wheel-loader": ("cargadores", "cargador sobre ruedas"),
    "all-terrain-crane": ("gruas", "grúa todo terreno"),
    "asphalt-paver": ("pavimentadoras", "pavimentadora de asfalto"),
    "boom-lift": ("plataformas-elevadoras", "plataforma elevadora de brazo"),
    "cold-planer": ("fresadoras", "fresadora de pavimento"),
    "crawler-crane": ("gruas", "grúa sobre orugas"),
    "forklift": ("montacargas", "montacargas"),
    "hydraulic-truck-crane": ("gruas", "grúa hidráulica sobre camión"),
    "material-handler": ("montacargas", "manipulador de materiales"),
    "pneumatic-roller": ("compactadores", "compactador neumático"),
    "rough-terrain-crane": ("gruas", "grúa todo terreno"),
    "scissor-lift": ("plataformas-elevadoras", "plataforma tipo tijera"),
    "static-smooth-drum-roller": ("compactadores", "compactador de tambor liso estático"),
    "telescopic-forklift": ("manipuladores-telescopicos", "manipulador telescópico"),
    "vibratory-compactor": ("compactadores", "compactador vibratorio"),
    "vibratory-smooth-drum-roller": ("compactadores", "compactador vibratorio de tambor liso"),
}
SOURCE_INDUSTRY = {source_type: "construction" for source_type in (
    "articulated-dump-truck", "compactor", "crawler-loader", "crawler-pipe-layer", "crawler-tractor",
    "elevating-motor-scraper", "hydraulic-excavator", "integrated-tool-carrier", "loader-backhoe",
    "midi-excavator", "mini-excavator", "mobile-excavator", "motor-grader", "motor-scraper",
    "multi-terrain-loader", "rock-truck", "shovel", "skid-steer-loader", "wheel-dozer", "wheel-loader",
)}
SOURCE_INDUSTRY.update({source_type: "lifting-material-handling" for source_type in (
    "all-terrain-crane", "boom-lift", "crawler-crane", "forklift", "hydraulic-truck-crane", "material-handler",
    "rough-terrain-crane", "scissor-lift", "telescopic-forklift",
)})
SOURCE_INDUSTRY.update({source_type: "asphalt-aggregate-concrete" for source_type in (
    "asphalt-paver", "cold-planer", "pneumatic-roller", "static-smooth-drum-roller", "vibratory-compactor",
    "vibratory-smooth-drum-roller",
)})
EXCLUDED_BRAND_SLUGS = {"aaa"}
BRAND_LABEL_OVERRIDES = {
    "asv": "ASV", "belaz": "BELAZ", "bomag": "BOMAG", "case": "CASE", "case-ih": "Case IH",
    "dressta": "Dressta", "hbxg": "HBXG", "ihi": "IHI", "jcb": "JCB", "jico": "JICO",
    "mecalac": "Mecalac", "moxy": "MOXY", "tcm": "TCM", "xcmg": "XCMG", "xcg": "XCG",
    "yto": "YTO",
}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def sitemap_locations(raw: bytes) -> list[str]:
    root = ET.fromstring(raw)
    return [node.text.strip() for node in root.iter() if node.tag.endswith("loc") and node.text]


def manufacturer_slugs(locations: list[str]) -> set[str]:
    prefix = "https://www.ritchiespecs.com/manufacturer/"
    return {url[len(prefix):].strip("/") for url in locations if url.startswith(prefix)}


def identifier_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).casefold()
    return "".join(char for char in text if char.isalnum() and not unicodedata.combining(char))


def catalogue_identity(record: dict) -> tuple[str, str, str]:
    """Use the same conservative identifier rules as the local catalogue."""
    brand = {"cat": "caterpillar", "deere": "johndeere", "volvoce": "volvo"}.get(
        identifier_key(record["brand"]), identifier_key(record["brand"]))
    return record["category_slug"], brand, identifier_key(record["model"])


def display_brand(slug: str) -> str:
    """Format the literal manufacturer-list slug without changing its identity."""
    return BRAND_LABEL_OVERRIDES.get(slug, " ".join(part.capitalize() for part in slug.split("-")))


def parse_model_url(url: str, manufacturers: set[str]) -> dict | None:
    """Accept only an unambiguous `brand-model-source-type` sitemap URL.

    Slugs are retained literally because the sitemap does not state OEM
    capitalization or punctuation. Normalizing pc-200 to PC200 would add a
    claim that the source did not make.
    """
    prefix = "https://www.ritchiespecs.com/model/"
    if not url.startswith(prefix):
        return None
    slug = url[len(prefix):].strip("/")
    source_type = next((item for item in sorted(CONSTRUCTION_TYPES, key=len, reverse=True)
                        if slug.endswith("-" + item)), None)
    if source_type is None:
        return None
    brand = next((item for item in sorted(manufacturers, key=len, reverse=True)
                  if slug.startswith(item + "-")), None)
    if brand is None:
        return None
    model = slug[len(brand) + 1:-(len(source_type) + 1)]
    if not model:
        return None
    category_slug, type_es = CONSTRUCTION_TYPES[source_type]
    return {
        "category_slug": category_slug, "brand": brand, "model": model,
        "variant": "", "generation": "", "market": "", "source": url,
        "source_title": "RitchieSpecs public sitemap model URL",
        "source_version": "public XML sitemap identity index", "retrieved_at": None,
        "provenance": {
            "authority": "RitchieSpecs public sitemap", "scope": "model_identity",
            "source_industry": SOURCE_INDUSTRY[source_type], "source_type": source_type, "type_es": type_es,
            "type_en": source_type.replace("-", " "), "brand_slug": brand,
            "model_slug": model, "specification_status": "not_retrieved",
            "note": "La URL individual figura en el sitemap público. Los slugs se conservan literalmente; esta fila no afirma especificaciones ni configuración de una unidad.",
        },
        "specs": {},
    }


def build_document(raw: bytes, retrieved_at: str | None = None, brand_labels: dict[str, str] | None = None) -> dict:
    locations = sitemap_locations(raw)
    manufacturers = manufacturer_slugs(locations)
    records = [record for url in locations if (record := parse_model_url(url, manufacturers))]
    matched_construction_url_occurrence_count = len(records)
    matched_construction_unique_url_count = len({record["source"] for record in records})
    unique = {}
    for record in sorted(records, key=lambda item: item["source"]):
        identity = catalogue_identity(record)
        prior = unique.get(identity)
        if prior is None:
            unique[identity] = record
            continue
        provenance = prior["provenance"]
        provenance.setdefault("additional_source_urls", []).append(record["source"])
        provenance.setdefault("additional_source_types", []).append(record["provenance"]["source_type"])
    records = [unique[identity] for identity in sorted(unique)]
    # A brand/model which RitchieSpecs places in more than one IMC category is
    # ambiguous for the category selector.  Do not silently choose one.
    model_categories = {}
    for record in records:
        key = catalogue_identity(record)[1:]
        model_categories.setdefault(key, set()).add(record["category_slug"])
    ambiguous = {key for key, categories in model_categories.items() if len(categories) > 1}
    ambiguous_records = [record for record in records if catalogue_identity(record)[1:] in ambiguous]
    excluded_brand_records = [record for record in records if record["provenance"]["brand_slug"] in EXCLUDED_BRAND_SLUGS]
    records = [record for record in records if catalogue_identity(record)[1:] not in ambiguous
               and record["provenance"]["brand_slug"] not in EXCLUDED_BRAND_SLUGS]
    brand_labels = brand_labels or {}
    for record in records:
        source_model = record["provenance"]["model_slug"]
        record["brand"] = brand_labels.get(record["provenance"]["brand_slug"],
                                             display_brand(record["provenance"]["brand_slug"]))
        # This is display-only formatting of the source slug; punctuation is
        # preserved and the raw source slug remains in provenance.
        record["model"] = source_model.upper()
    retrieved_at = retrieved_at or dt.date.today().isoformat()
    for record in records:
        record["retrieved_at"] = retrieved_at
    counts = Counter(record["provenance"]["source_type"] for record in records)
    return {
        "schema_version": 1, "catalogue_kind": "model_identity_index",
        "source": {
            "provider": "RitchieSpecs", "sitemap": SITEMAP_URL,
            "robots": "https://www.ritchiespecs.com/robots.txt", "retrieved_at": retrieved_at,
            "sitemap_sha256": hashlib.sha256(raw).hexdigest(),
            "declared_model_url_count": sum("/model/" in url for url in locations),
            "matched_construction_url_occurrence_count": matched_construction_url_occurrence_count,
            "matched_construction_unique_url_count": matched_construction_unique_url_count,
            "matching_construction_model_url_count": len({record["source"] for record in records}) + sum(
                len(record["provenance"].get("additional_source_urls", [])) for record in records),
            "construction_family_count": len(CONSTRUCTION_TYPES),
            "construction_model_identity_count": len(records),
            "excluded_ambiguous_category_model_count": len(ambiguous_records),
            "excluded_unknown_brand_model_count": len(excluded_brand_records),
            "specification_coverage": "0; this release is an identity index. Do not infer measurements from a slug.",
        },
        "counts_by_source_type": dict(sorted(counts.items())), "references": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-sitemap", type=Path)
    parser.add_argument("--brand-labels", type=Path,
                        help="Optional verified brand-label JSON; source slugs remain in provenance.")
    parser.add_argument("--retrieved-at", help="ISO date for reproducible replays (default: today).")
    args = parser.parse_args()
    raw = args.input_sitemap.read_bytes() if args.input_sitemap else fetch(SITEMAP_URL)
    brand_labels = json.loads(args.brand_labels.read_text(encoding="utf-8"))["labels"] if args.brand_labels else None
    document = build_document(raw, args.retrieved_at, brand_labels)
    if document["source"]["construction_model_identity_count"] < 5_460:
        raise SystemExit("The source no longer supplies the minimum identity coverage; refusing a partial release.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(document['references'])} unique construction model identities to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
