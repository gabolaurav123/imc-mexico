"""Safe retrieval of administrator-reviewed technical model references.

This library is intentionally a local fallback.  It never fetches a URL and it
does not infer a model, variant, market or a unit characteristic.
"""
from __future__ import annotations

from copy import deepcopy
from .research import identifier_key, normalize_direct_fields, ResearchField


def _value(data, key):
    source = data.get("data", data) if isinstance(data, dict) else {}
    return source.get(key) if isinstance(source, dict) else None


def _market(data):
    """Return a known market only from a user-confirmed location country."""
    if not isinstance(data, dict):
        return ""
    provenance = data.get("provenance", {})
    meta = provenance.get("location_country", {}) if isinstance(provenance, dict) else {}
    if not isinstance(meta, dict) or (meta.get("source") != "user" and meta.get("review") != "confirmed"):
        return ""
    country = _value(data, "location_country")
    country_key = identifier_key(country)
    # Deliberate aliases only. An unknown country is never guessed as MX.
    return {"mx": "MX", "mexico": "MX", "estadosunidosmexicanos": "MX",
            "us": "US", "usa": "US", "unitedstates": "US", "estadosunidos": "US",
            "ca": "CA", "canada": "CA"}.get(country_key, "")


def _trusted_variant(data):
    if not isinstance(data, dict):
        return ""
    provenance = data.get("provenance", {})
    meta = provenance.get("variant", {}) if isinstance(provenance, dict) else {}
    if not isinstance(meta, dict) or (meta.get("source") != "user" and meta.get("review") not in {"clear", "confirmed"}):
        return ""
    return _value(data, "variant") or ""


def _knowledge_context(result, snapshot):
    """Use a clear result variant only when the snapshot does not already own it."""
    context = deepcopy(snapshot) if isinstance(snapshot, dict) else {"data": {}, "provenance": {}}
    context.setdefault("data", {})
    context.setdefault("provenance", {})
    variant_meta = context["provenance"].get("variant", {})
    if _trusted_variant(context) or (isinstance(variant_meta, dict) and
            (variant_meta.get("source") == "user" or variant_meta.get("review") == "confirmed")):
        return context
    result_meta = result.get("provenance", {}).get("variant", {}) if isinstance(result, dict) else {}
    result_value = result.get("data", {}).get("variant") if isinstance(result, dict) else None
    if isinstance(result_meta, dict) and result_value and (result_meta.get("source") == "user" or result_meta.get("review") in {"clear", "confirmed"}):
        context["data"]["variant"] = result_value
        context["provenance"]["variant"] = deepcopy(result_meta)
    return context


def _category(category):
    if getattr(category, "pk", None):
        return category
    if not isinstance(category, str) or not category.strip():
        return None
    from .models import Category
    return Category.objects.filter(name__iexact=category.strip()).first() or Category.objects.filter(slug__iexact=category.strip()).first()


def retrieve_technical_references(snapshot, category=None, identity=None):
    """Return active approved refs only when brand/model/variant/market match.

    Variant and market must both agree after conservative identifier
    normalization, including the empty value. This prevents a generic or
    near-named catalogue variant from crossing into a unit's research result.
    """
    from .models import TechnicalReference
    source = snapshot.get("data", snapshot) if isinstance(snapshot, dict) else {}
    category = _category(category or getattr(snapshot, "category", None))
    identity = identity or {}
    brand, model = identity.get("brand") or _value(source, "brand"), identity.get("model") or _value(source, "model")
    variant, market = _trusted_variant(snapshot), _market(snapshot)
    if not category or not brand or not model:
        return []
    queryset = TechnicalReference.objects.filter(category=category, active=True,
                                                 review=TechnicalReference.Review.APPROVED,
                                                 brand__iexact=str(brand).strip(), model__iexact=str(model).strip())
    matched = []
    for reference in queryset:
        # A generation-specific reference cannot silently become a generic
        # model reference when the unit's generation is unknown.
        if reference.generation and identifier_key(reference.generation) != identifier_key(_value(source, "generation")):
            continue
        if identifier_key(reference.variant) != identifier_key(variant):
            continue
        if identifier_key(reference.market) != identifier_key(market):
            continue
        matched.append(reference)
    return matched


def knowledge_sources(snapshot, category=None, identity=None):
    """Detached references suitable for a worker to inspect or normalize."""
    return [{"id": reference.pk, "category": reference.category_id, "brand": reference.brand,
             "model": reference.model, "variant": reference.variant, "generation": reference.generation,
             "market": reference.market, "period_from": reference.period_from, "period_to": reference.period_to,
             "specs": deepcopy(reference.specs), "provenance": deepcopy(reference.provenance),
             "source": reference.source, "source_title": reference.source_title,
             "source_version": reference.source_version, "retrieved_at": reference.retrieved_at.isoformat()}
            for reference in retrieve_technical_references(snapshot, category, identity)]


def research_from_knowledge(result, snapshot, category=None, identity=None):
    """Create the existing signed research manifest from exact local matches.

    Each stored spec must include a literal ``value`` and ``evidence``.  The
    existing research normalizer rechecks the source URL, identity, field value,
    and evidence before any value can enter a draft.
    """
    identity = {"brand": (identity or {}).get("brand") or _value(snapshot, "brand"),
                "model": (identity or {}).get("model") or _value(snapshot, "model"),
                "serial": (identity or {}).get("serial")}
    if not identity["brand"] or not identity["model"]:
        return None
    context = _knowledge_context(result, snapshot)
    references = retrieve_technical_references(context, category, identity)
    if not references:
        return None
    sources, passages, fields, titles = [], [], [], {}
    for reference in references:
        url = reference.source
        title = reference.source_title
        sources.append({"url": url, "title": title})
        titles[url] = title
        for key, item in reference.specs.items():
            if not isinstance(item, dict) or not isinstance(item.get("value"), (str, int, float)):
                continue
            evidence = item.get("evidence")
            if not isinstance(evidence, str):
                continue
            value = str(item["value"])
            passages.append({"source_url": url, "text": evidence})
            fields.append(ResearchField(key=str(key), value=value, scope="model", source_url=url,
                                        evidence=evidence, matched_serial=None,
                                        matched_brand=reference.brand, matched_model=reference.model))
    if not fields:
        return None
    search_text = "\n".join(item["text"] for item in passages)
    return normalize_direct_fields(identity, "model", sources, search_text, passages, titles, direct_fields=fields)
