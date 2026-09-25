"""Reviewed, local reference proposals for an unread model suffix.

This module deliberately sits beside exact-model research and valuation.  A
literal family label from an accepted photograph may find *family* records
(for example ``320D`` and ``320D L``), but it never identifies the unit as a
specific variant, copies technical specifications, or proposes an asking
price.  It performs no network or model call.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit
import unicodedata

from django.core import signing
from django.db.models import Q
from django.utils import timezone

from .market_catalogue import MAX_REFERENCE_AGE_DAYS
from .market_observations import latest_market_observations
from .models import Category, MarketReference, TechnicalReference
from .research import (_accepted_visual_model_hint, _brand_aliases, _brand_key,
                       _retrieved_url_identity, documented_model_period,
                       human_declared_data, identifier_key, safe_public_url)
from .valuation import _MARKET_NAMES, _configuration_key, configuration_signature


FAMILY_REFERENCE_VERSION = "imc-family-reference-2026-09-v1"
FAMILY_REFERENCE_LABEL = "Referencia orientativa de familia; variante de la unidad pendiente de confirmar"
SIGNING_SALT = "portal.family_reference.manifest.v1"
FAMILY_FIELDS = frozenset({
    "model_family", "estimated_year_from", "estimated_year_to", "estimated_year_basis",
    "estimate_min", "estimate_max", "estimate_currency", "estimate_date", "estimate_market",
    "estimate_basis", "estimate_missing_info",
})
_ESTIMATE_FIELDS = frozenset({"estimate_min", "estimate_max", "estimate_currency", "estimate_date",
                              "estimate_market", "estimate_basis", "estimate_missing_info"})
_ESTIMATE_CORE_FIELDS = _ESTIMATE_FIELDS - {"estimate_missing_info"}


def _category(value):
    if getattr(value, "pk", None) and getattr(value, "active", False):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    return (Category.objects.filter(active=True, name__iexact=value.strip()).first()
            or Category.objects.filter(active=True, slug__iexact=value.strip()).first())


def is_family_member(model, family):
    """Allow only the reviewed 320D-style base and L/LC suffix spellings.

    A number after the family (``320D2``) is another model, never a child.
    This intentionally does not use a generic startswith match.
    """
    member, base = identifier_key(model), identifier_key(family)
    if not member or not base or not member.startswith(base):
        return False
    suffix = member[len(base):]
    return suffix in {"", "l", "lc"}


def _accepted_visual_family(result, category):
    """Return only a literal doubtful label tied to an accepted machine photo."""
    if not isinstance(result, dict):
        return None
    hint = _accepted_visual_model_hint(result)
    if not hint:
        return None
    accepted = set(result.get("relevance", {}).get("accepted_asset_ids", []))
    data, provenance = result.get("data", {}), result.get("provenance", {})
    brand = data.get("brand") if isinstance(data, dict) else None
    meta = provenance.get("brand", {}) if isinstance(provenance, dict) else {}
    if (not isinstance(brand, str) or not brand.strip() or not isinstance(meta, dict)
            or meta.get("component") != "machine" or meta.get("review") != "clear"
            or meta.get("source") not in {"image", "plate"} or meta.get("asset_id") not in accepted):
        return None
    if not category:
        return None
    return {"brand": " ".join(brand.split()), "model_family": hint["value"],
            "category": category.name, "category_id": category.pk, "scope": "family",
            "asset_id": hint.get("asset_id"), "evidence": hint.get("evidence", "")}


def _condition_context(result, snapshot):
    """Use an observed/declared class only to reject a different listing class."""
    aliases = {"nueva": "new", "nuevo": "new", "new": "new", "usada": "used", "usado": "used",
               "used": "used", "reacondicionada": "refurbished", "reacondicionado": "refurbished",
               "refurbished": "refurbished", "para reparacion": "for_repair", "for repair": "for_repair"}

    def normalized(value):
        text = " ".join(str(value or "").split()).casefold()
        text = "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))
        return aliases.get(text)

    declared = human_declared_data(snapshot)
    for key in ("condition", "usage_condition"):
        if key in declared and normalized(declared[key]):
            return normalized(declared[key]), "owner"
    data, provenance = result.get("data", {}), result.get("provenance", {})
    for key in ("condition", "usage_condition"):
        meta = provenance.get(key, {}) if isinstance(provenance, dict) else {}
        value = data.get(key) if isinstance(data, dict) else None
        if (normalized(value) and isinstance(meta, dict) and meta.get("component") == "machine"
                and meta.get("source") in {"image", "plate", "visual_proposal"}
                and meta.get("review") in {"clear", "confirmed", "needs_review"}):
            return normalized(value), "apparent"
    return None, "unknown"


def _brand_query(brand, prefix):
    query = Q()
    for alias in _brand_aliases(brand):
        query |= Q(**{prefix + "__iexact": str(alias).strip()})
    return query


def _period_records(identity, category):
    records = []
    rows = (TechnicalReference.objects.filter(category=category, active=True,
             review=TechnicalReference.Review.APPROVED)
            .filter(_brand_query(identity["brand"], "brand")))
    for row in rows:
        if (not is_family_member(row.model, identity["model_family"])
                or not isinstance(row.provenance, dict)
                or not row.period_from or not row.period_to):
            continue
        evidence = row.provenance.get("period_evidence")
        if (not isinstance(evidence, str)
                or documented_model_period(evidence) != (str(row.period_from), str(row.period_to))):
            continue
        url = safe_public_url(row.source)
        if not url:
            continue
        records.append({"model": row.model, "from": row.period_from, "to": row.period_to,
                        "url": url, "title": row.source_title, "evidence": evidence[:800]})
    return records


def _family_unit_key(row):
    unit = " ".join(str(row.unit_key or "").split()).casefold()
    if unit:
        return "unit", unit
    return "source", _retrieved_url_identity(row.source)


def _market_rows(identity, category):
    today = timezone.localdate()
    rows = (MarketReference.objects.filter(active=True, review=MarketReference.Review.APPROVED,
             equipment_model__active=True, equipment_model__brand__active=True,
             equipment_model__category=category)
            .filter(_brand_query(identity["brand"], "equipment_model__brand__name"))
            .select_related("equipment_model", "equipment_model__brand"))
    newest, seen = [], set()
    # The normal market selector includes model ID in its key.  At family
    # scope that could treat a corrected 320D/320DL record as two units, so
    # deduplicate on its actual unit key/source before compatibility grouping.
    for row in latest_market_observations(rows, today=today):
        key = _family_unit_key(row)
        if key in seen:
            continue
        seen.add(key)
        if row.retrieved_at < today - timedelta(days=MAX_REFERENCE_AGE_DAYS):
            continue
        if (not is_family_member(row.equipment_model.name, identity["model_family"])
                or row.currency not in {"USD", "MXN", "EUR"}
                or row.market not in _MARKET_NAMES
                or row.price_type not in {"asking", "sold"}
                or row.condition not in {"new", "used", "refurbished", "for_repair"}
                or not isinstance(row.configurations, dict)
                or not isinstance(row.evidence, str) or not row.evidence.strip()
                or not safe_public_url(row.source)):
            continue
        try:
            if Decimal(row.price) <= 0:
                continue
        except (ArithmeticError, TypeError, ValueError):
            continue
        newest.append(row)
    return newest


def _select_market_group(rows, condition=None):
    groups = defaultdict(list)
    for row in rows:
        if condition and row.condition != condition:
            continue
        group = (row.currency, row.market, row.price_type, row.condition,
                 configuration_signature(row.configurations))
        groups[group].append(row)
    eligible = []
    for group, values in groups.items():
        # Without a stable unit key, a seller can contribute only one listing.
        kept, hosts = [], set()
        for row in sorted(values, key=lambda item: (-item.retrieved_at.toordinal(), -item.pk)):
            host = (urlsplit(row.source).hostname or "").removeprefix("www.").lower()
            unit_kind, _ = _family_unit_key(row)
            if host in hosts and unit_kind != "unit":
                continue
            kept.append(row)
            hosts.add(host)
        if len(kept) >= 2:
            eligible.append((group, kept))
    if not eligible:
        return None
    eligible.sort(key=lambda item: (-len(item[1]), item[0]))
    return eligible[0]


def _manifest(value):
    return {key: value.get(key) for key in ("version", "status", "label", "identity", "fields",
                                              "comparables", "sources")}


def _seal(value):
    value["proof"] = signing.Signer(salt=SIGNING_SALT).sign_object(_manifest(value), compress=True)
    return value


def is_validated_family_reference(value):
    if not isinstance(value, dict) or value.get("version") != FAMILY_REFERENCE_VERSION:
        return False
    if value.get("status") != "family_reference" or value.get("label") != FAMILY_REFERENCE_LABEL:
        return False
    identity, fields = value.get("identity"), value.get("fields")
    if (not isinstance(identity, dict) or identity.get("scope") != "family"
            or not isinstance(identity.get("brand"), str) or not identity["brand"].strip()
            or not isinstance(identity.get("model_family"), str) or not identity["model_family"].strip()
            or not isinstance(fields, dict) or set(fields) - FAMILY_FIELDS
            or fields.get("model_family") != identity["model_family"]):
        return False
    if any(key in fields for key in _ESTIMATE_CORE_FIELDS) and not _ESTIMATE_CORE_FIELDS.issubset(fields):
        return False
    if {"estimated_year_from", "estimated_year_to"} & set(fields):
        if not {"estimated_year_from", "estimated_year_to", "estimated_year_basis"}.issubset(fields):
            return False
        if (type(fields["estimated_year_from"]) is not int or type(fields["estimated_year_to"]) is not int
                or fields["estimated_year_from"] > fields["estimated_year_to"]):
            return False
    try:
        return signing.Signer(salt=SIGNING_SALT).unsign_object(value.get("proof", "")) == _manifest(value)
    except (signing.BadSignature, TypeError, ValueError):
        return False


def family_identity_matches(data, manifest):
    """Keep a signed family proposal tied to the surviving brand/family/model."""
    if not is_validated_family_reference(manifest) or not isinstance(data, dict):
        return False
    identity = manifest["identity"]
    if _brand_key(data.get("brand")) != _brand_key(identity["brand"]):
        return False
    stored_family = data.get("model_family")
    if stored_family not in (None, "") and identifier_key(stored_family) != identifier_key(identity["model_family"]):
        return False
    model = data.get("model")
    return model in (None, "") or is_family_member(model, identity["model_family"])


def build_family_reference(result, snapshot=None, category=None):
    """Build a signed family-only local proposal, or ``None`` when unsupported."""
    category = _category(category or (result or {}).get("category"))
    identity = _accepted_visual_family(result, category)
    if not identity:
        return None
    periods = _period_records(identity, category)
    condition, condition_basis = _condition_context(result, snapshot)
    identity.update(condition=condition, condition_basis=condition_basis, members=[])
    market_rows = _market_rows(identity, category)
    market_group = _select_market_group(market_rows, condition)
    fields = {
        "model_family": identity["model_family"],
        # Replace the generic exact-model gap even when this particular family
        # has no usable local market range yet.  This is not a price proposal.
        "estimate_missing_info": ("La variante exacta, horas y ubicación ayudarían a ajustar el rango de la familia. "
                                  "No se identificó todavía la variante de esta unidad."),
    }
    sources = []
    if periods:
        fields.update(estimated_year_from=min(item["from"] for item in periods),
                      estimated_year_to=max(item["to"] for item in periods),
                      estimated_year_basis=("Intervalos publicados para miembros de la familia "
                                            f"{identity['brand']} {identity['model_family']}; no identifican "
                                            "la variante ni el año de esta unidad, ni prueban producción continua."))
        sources = [{"url": item["url"], "title": item["title"], "model": item["model"],
                    "period_from": item["from"], "period_to": item["to"]} for item in periods[:8]]
        identity["members"].extend(item["model"] for item in periods)
    comparables = []
    if market_group:
        (currency, market, price_type, comparable_condition, configuration), selected = market_group
        prices = sorted(Decimal(item.price) for item in selected[:6])
        comparables = [{"url": safe_public_url(item.source), "title": item.source_title,
                        "price": format(Decimal(item.price), ".2f"), "currency": item.currency,
                        "market": item.market, "price_type": item.price_type, "condition": item.condition,
                        "retrieved_at": item.retrieved_at.isoformat(), "model": item.equipment_model.name,
                        "configurations": deepcopy(item.configurations)} for item in selected[:6]]
        identity["members"].extend(item.equipment_model.name for item in selected)
        sale_label = ("Precios finales publicados de ventas" if price_type == "sold"
                      else "Precios anunciados de oferta; no acreditan una venta cerrada")
        condition_note = (f"La condición usada para comparar es {condition}; no confirma funcionamiento."
                          if condition else
                          f"Los comparables se clasifican como {comparable_condition}; no se atribuye esa condición a la unidad.")
        fields.update(estimate_min=format(min(prices), ".2f"), estimate_max=format(max(prices), ".2f"),
                      estimate_currency=currency, estimate_date=max(item.retrieved_at for item in selected).isoformat(),
                      estimate_market=_MARKET_NAMES[market],
                      estimate_basis=(f"{FAMILY_REFERENCE_LABEL}. {sale_label}: {len(prices)} comparables independientes "
                                      f"de la familia en {market}; misma moneda, tipo de precio, condición y configuración documentada. "
                                      f"{condition_note} No combina ventas con anuncios ni aplica ajustes."),
                      estimate_missing_info=("Confirma el sufijo del modelo, condición, año, horas y configuración real "
                                             "antes de fijar un precio. No es una tasación de esta unidad."))
    identity["members"] = sorted(set(identity["members"]), key=identifier_key)
    if len(fields) == 2:
        return None
    return _seal({"version": FAMILY_REFERENCE_VERSION, "status": "family_reference", "label": FAMILY_REFERENCE_LABEL,
                  "identity": identity, "fields": fields, "comparables": comparables, "sources": sources})


def _human_or_confirmed(snapshot, result, key):
    declared = human_declared_data(snapshot)
    if key in declared:
        return True
    meta = (result.get("provenance", {}) if isinstance(result, dict) else {}).get(key, {})
    return isinstance(meta, dict) and (meta.get("source") == "user" or meta.get("review") == "confirmed")


def merge_family_reference(result, family, snapshot=None):
    """Attach independently reviewable fields; never fill model, year, price or specs."""
    if not isinstance(result, dict) or not is_validated_family_reference(family):
        return result
    if not family_identity_matches(result.get("data", {}), family):
        return result
    result["family_reference"] = deepcopy(family)
    identity, values = family["identity"], family["fields"]
    result.setdefault("data", {})
    result.setdefault("provenance", {})
    result.setdefault("fields", [])
    period_keys = {"estimated_year_from", "estimated_year_to", "estimated_year_basis"}
    locked_period = any(_human_or_confirmed(snapshot, result, key) for key in period_keys | {"year"})
    for key, value in values.items():
        if key == "model_family":
            pass
        elif key in period_keys and locked_period:
            continue
        elif _human_or_confirmed(snapshot, result, key):
            continue
        meta = {"source": "family_reference", "review": "needs_review", "scope": "family",
                "identity_scope": "family", "component": "machine", "asset_id": identity.get("asset_id"),
                "evidence": identity.get("evidence", ""), "label": FAMILY_REFERENCE_LABEL,
                "confidence": "family_reference"}
        result["data"][key] = value
        result["provenance"][key] = meta
        result["fields"].append({"key": key, "value": value, **meta})
    return result


def is_validated_family_field(result, key, value, meta):
    """Trust boundary used by draft auto-apply; values must equal the seal."""
    if key not in FAMILY_FIELDS or not isinstance(meta, dict):
        return False
    if (meta.get("source") != "family_reference" or meta.get("review") != "needs_review"
            or meta.get("scope") != "family" or meta.get("identity_scope") != "family"
            or meta.get("component") != "machine"):
        return False
    family = result.get("family_reference", {}) if isinstance(result, dict) else {}
    if not (is_validated_family_reference(family) and family_identity_matches(result.get("data", {}), family)
            and key in family["fields"]
            and meta.get("asset_id") == family["identity"].get("asset_id")
            and meta.get("evidence") == family["identity"].get("evidence")):
        return False
    if key in {"estimated_year_from", "estimated_year_to", "estimate_min", "estimate_max"}:
        try:
            return Decimal(str(value)) == Decimal(str(family["fields"][key]))
        except (ArithmeticError, ValueError):
            return False
    return str(value) == str(family["fields"][key])
