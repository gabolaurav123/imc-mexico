import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "import_ritchiespecs_construction.py"
SPEC = importlib.util.spec_from_file_location("ritchiespecs_import", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_parse_model_url_requires_an_unambiguous_brand_and_construction_type():
    parsed = MODULE.parse_model_url(
        "https://www.ritchiespecs.com/model/caterpillar-365c-l-hydraulic-excavator",
        {"caterpillar", "cat"})
    assert parsed["brand"] == "caterpillar"
    assert parsed["model"] == "365c-l"
    assert parsed["category_slug"] == "excavadoras"
    assert parsed["provenance"]["source_type"] == "hydraulic-excavator"
    assert parsed["specs"] == {}
    assert MODULE.parse_model_url(
        "https://www.ritchiespecs.com/model/caterpillar-365c-l-utility-tractor",
        {"caterpillar"}) is None


def test_build_document_deduplicates_urls_and_preserves_source_slug():
    raw = b'''<?xml version="1.0"?><urlset>
      <url><loc>https://www.ritchiespecs.com/manufacturer/caterpillar</loc></url>
      <url><loc>https://www.ritchiespecs.com/model/caterpillar-365c-l-hydraulic-excavator</loc></url>
      <url><loc>https://www.ritchiespecs.com/model/caterpillar-365c-l-hydraulic-excavator</loc></url>
    </urlset>'''
    document = MODULE.build_document(raw, "2026-10-06", {"caterpillar": "Caterpillar"})
    assert document["source"]["construction_model_identity_count"] == 1
    assert document["references"][0]["retrieved_at"] == "2026-10-06"
    assert document["references"][0]["provenance"]["model_slug"] == "365c-l"


def test_catalogue_identity_collapses_presentation_only_duplicates():
    first = {"category_slug": "excavadoras", "brand": "cat", "model": "320-d"}
    second = {"category_slug": "excavadoras", "brand": "Caterpillar", "model": "320 d"}
    assert MODULE.catalogue_identity(first) == MODULE.catalogue_identity(second)


def test_generated_release_has_no_catalogue_identity_duplicates():
    release = Path(__file__).parents[2] / "knowledge" / "new_ritchiespecs_construction_identities_2026-10-06.json"
    document = json.loads(release.read_text(encoding="utf-8"))
    records = document["references"]
    identities = {MODULE.catalogue_identity(record) for record in records}
    assert len(records) == 10360
    assert len(identities) == len(records)
    assert document["source"]["construction_model_identity_count"] == len(records)
    assert all(record["specs"] == {} for record in records)
    assert all(record["provenance"]["specification_status"] == "not_retrieved" for record in records)
    source_categories = {}
    for record in records:
        source_identity = (record["provenance"]["brand_slug"], record["provenance"]["model_slug"])
        source_categories.setdefault(source_identity, set()).add(record["category_slug"])
    assert all(len(categories) == 1 for categories in source_categories.values())


def test_komatsu_release_contains_only_cited_nonempty_metric_specs():
    release = Path(__file__).parents[2] / "knowledge" / "new_komatsu_current_specs_2026-10-06.json"
    document = json.loads(release.read_text(encoding="utf-8"))
    records = document["references"]
    assert len(records) == 120
    assert document["source"]["references_with_supported_metric_specs"] == len(records)
    assert document["source"]["excluded_exact_duplicate_with_existing_bundle"] == 2
    assert len({record["source"] for record in records}) == len(records)
    assert all(record["brand"] == "Komatsu" and record["specs"] for record in records)
    assert all(record["source"].startswith("https://www.komatsu.com/en-us/products/equipment/") for record in records)
    assert all(" kW kW" not in spec["value"] for record in records for spec in record["specs"].values())
    assert all("capacity" not in record["specs"] for record in records)
    assert all(record["specs"]["travel_speed"]["value"].endswith(" kph")
               for record in records if "travel_speed" in record["specs"])
