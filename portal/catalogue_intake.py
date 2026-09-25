"""Local, reviewed catalogue intake for a fiche without unit media.

The catalogue can describe a model.  It must never become evidence about a
particular unit, so this module deliberately leaves unit-only fields empty.
"""
from __future__ import annotations

from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.utils import timezone

from .models import Category, EquipmentModel, TechnicalReference
from .services import DATA_FIELDS


CATALOGUE_BASIS = "catalogue_intake"
MODEL_SOURCE = "web_model"
_UNIT_ONLY_FIELDS = frozenset({
    "year", "hours", "hours_basis", "hours_recorded_at", "kilometers", "serial",
    "location", "location_country", "location_region", "location_city", "condition",
    "price", "contact_public", "notes",
})


def _references_for_model(model):
    return list(TechnicalReference.objects.filter(
        equipment_model=model, category=model.category, active=True,
        review=TechnicalReference.Review.APPROVED,
    ).order_by("pk"))


def catalogue_choices(categories=None):
    """Serialize only exact, approved model references for the start form."""
    category_ids = None
    if categories is not None:
        category_ids = {category.pk for category in categories if category.active}
    queryset = (EquipmentModel.objects.filter(active=True, brand__active=True,
        category__active=True, technical_references__active=True,
        technical_references__review=TechnicalReference.Review.APPROVED)
        .select_related("brand", "category").distinct().order_by("category__name", "brand__name", "name"))
    if category_ids is not None:
        queryset = queryset.filter(category_id__in=category_ids)
    return [{"id": model.pk, "category": model.category_id, "brand": model.brand.name,
             "name": model.name} for model in queryset]


def selected_catalogue_model(category_id, model_id):
    try:
        category = Category.objects.get(pk=category_id, active=True)
        model = EquipmentModel.objects.select_related("brand", "category").get(
            pk=model_id, active=True, brand__active=True, category=category)
    except (Category.DoesNotExist, EquipmentModel.DoesNotExist, TypeError, ValueError):
        raise ValidationError("Selecciona un modelo disponible para el tipo de máquina elegido.")
    references = _references_for_model(model)
    if not references:
        raise ValidationError("Ese modelo no tiene una referencia técnica aprobada para preparar una ficha sin fotografías.")
    return category, model, references


def _source_meta(reference, *, review="needs_review", label="Referencia técnica documentada del modelo"):
    return {
        "source": MODEL_SOURCE, "review": review, "scope": "model", "basis": CATALOGUE_BASIS,
        "source_url": reference.source, "source_title": reference.source_title,
        "source_date": reference.retrieved_at.isoformat(), "evidence": reference.source_title,
        "label": label,
    }


def _agreed_specs(references):
    """Keep a value only when every included source agrees on it exactly."""
    values = {}
    for reference in references:
        for key, item in (reference.specs or {}).items():
            if key not in DATA_FIELDS or key in (_UNIT_ONLY_FIELDS | {"currency", "description"}) or not isinstance(item, dict):
                continue
            value, evidence = item.get("value"), item.get("evidence")
            if not isinstance(value, (str, int, float)) or isinstance(value, bool) or not isinstance(evidence, str) or not evidence.strip():
                continue
            values.setdefault(key, []).append((str(value), reference, evidence.strip()))
    result = {}
    for key, records in values.items():
        if len({value for value, _, _ in records}) != 1:
            continue
        value, reference, evidence = records[0]
        result[key] = (value, {**_source_meta(reference), "evidence": evidence[:12000]})
    return result


def _period(references):
    rows = []
    for reference in references:
        evidence = (reference.provenance or {}).get("period_evidence")
        if reference.period_from and reference.period_to and isinstance(evidence, str) and evidence.strip():
            rows.append((reference, evidence.strip()))
    if not rows:
        return {}, {}
    start, end = min(row.period_from for row, _ in rows), max(row.period_to for row, _ in rows)
    reference, evidence = rows[0]
    data = {
        "estimated_year_from": start,
        "estimated_year_to": end,
        "estimated_year_basis": ("Periodo de producción documentado para el modelo; no confirma "
                                  "el año de esta unidad."),
    }
    provenance = {key: {**_source_meta(reference, label="Periodo documentado del modelo"),
                        "evidence": evidence[:12000]} for key in data}
    return data, provenance


def _market_range(model, category):
    """Use the existing signed local market library, never a paid/web call."""
    from .market_catalogue import valuation_from_library
    valuation = valuation_from_library({"brand": model.brand.name, "model": model.name,
                                        "condition": None, "market_hint": None,
                                        "configurations": {}, "compatibility": {}}, category)
    if not valuation:
        return {}, {}
    fields = valuation.get("fields", {})
    allowed = {"estimate_min", "estimate_max", "estimate_currency", "estimate_date", "estimate_market",
               "estimate_basis", "estimate_missing_info"}
    data = {key: value for key, value in fields.items() if key in allowed and value not in (None, "")}
    if not data:
        return {}, {}
    reference = next(iter(_references_for_model(model)), None)
    if not reference:
        return {}, {}
    provenance = {key: {**_source_meta(reference, label="Rango de mercado de modelos comparables"),
                        "source": "valuation", "evidence": str(data.get("estimate_basis") or reference.source_title)[:12000]}
                  for key in data}
    return data, provenance


def catalogue_proposal(category_id, model_id):
    """Return editable model reference data and its persisted provenance."""
    category, model, references = selected_catalogue_model(category_id, model_id)
    primary = references[0]
    data = {"brand": model.brand.name, "model": model.name, "currency": "USD",
            "description": ("Ficha iniciada con referencias documentadas del modelo. Confirma las "
                            "características, el año, las horas, el estado y la ubicación de esta unidad.")}
    provenance = {
        "brand": _source_meta(primary, review="confirmed", label="Modelo seleccionado del catálogo"),
        "model": _source_meta(primary, review="confirmed", label="Modelo seleccionado del catálogo"),
        "currency": {"source": "system", "review": "needs_review"},
        "description": {"source": "system", "review": "needs_review"},
    }
    for key, (value, meta) in _agreed_specs(references).items():
        data[key], provenance[key] = value, meta
    period_data, period_provenance = _period(references)
    data.update(period_data); provenance.update(period_provenance)
    market_data, market_provenance = _market_range(model, category)
    data.update(market_data); provenance.update(market_provenance)
    # These are intentionally absent even if a catalogue or market row contains them.
    for key in _UNIT_ONLY_FIELDS:
        data.pop(key, None); provenance.pop(key, None)
    from .research import compose_description
    description_sources = {key: {**meta, "source": "web"} if meta.get("source") == MODEL_SOURCE else meta
                           for key, meta in provenance.items()}
    data["description"] = compose_description(data, description_sources, category=category.name)
    return {"category": category, "model": model, "data": data, "provenance": provenance,
            "reference_count": len(references), "mode": "catalogue"}


def catalogue_reference_ready(machine):
    """A persisted exact-model selection is the only no-media preparation mode."""
    if not machine.category_id or not isinstance(machine.data, dict) or not isinstance(machine.provenance, dict):
        return False
    brand, model = machine.data.get("brand"), machine.data.get("model")
    meta = machine.provenance.get("model", {})
    if not (isinstance(brand, str) and brand.strip() and isinstance(model, str) and model.strip()
            and isinstance(meta, dict) and meta.get("source") == MODEL_SOURCE
            and meta.get("scope") == "model" and meta.get("basis") == CATALOGUE_BASIS
            and isinstance(meta.get("source_url"), str) and meta["source_url"].startswith(("https://", "http://"))):
        return False
    if catalogue_reference_stale(machine):
        return False
    return EquipmentModel.objects.filter(category_id=machine.category_id, active=True, brand__active=True,
        brand__name__iexact=brand.strip(), name__iexact=model.strip(), technical_references__active=True,
        technical_references__review=TechnicalReference.Review.APPROVED).exists()


def catalogue_reference_stale(machine):
    """Detect retained model fields after the owner has changed the identity.

    Editing a field through the normal draft endpoint turns its provenance into
    ``user``.  The remaining catalogue specifications keep their original
    citation, so compare every retained citation against the current identity
    before another preparation, share, or no-media submission can rely on it.
    """
    if not isinstance(machine.data, dict) or not isinstance(machine.provenance, dict):
        return False
    urls = {meta.get("source_url") for key, meta in machine.provenance.items()
            if machine.data.get(key) not in (None, "") and isinstance(meta, dict)
            and meta.get("basis") == CATALOGUE_BASIS and isinstance(meta.get("source_url"), str)}
    if not urls:
        return False
    brand, model = machine.data.get("brand"), machine.data.get("model")
    if not machine.category_id or not isinstance(brand, str) or not brand.strip() or not isinstance(model, str) or not model.strip():
        return True
    from .research import _brand_key, identifier_key
    matches = {reference.source for reference in TechnicalReference.objects.filter(category_id=machine.category_id,
        source__in=urls) if _brand_key(reference.brand) == _brand_key(brand)
        and identifier_key(reference.model) == identifier_key(model)}
    return not urls.issubset(matches)
