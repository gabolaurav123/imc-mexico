"""One-way projection from editable listing data to canonical search values.

Editable values continue to live in ``Machine.data``.  ``data['structured']``
is an immutable-at-snapshot read model produced by this module, never a second
set of form fields.  Ambiguous legacy strings deliberately project to ``None``.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re

from django.core.exceptions import ValidationError

MAX_YEAR = 2200
_DECIMAL = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
_MEASURE = re.compile(r"^\s*([+-]?(?:\d+(?:[.,]\d+)?))\s*([A-Za-z0-9³^]+)\s*$", re.I)
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_MAXIMUMS = {"hours": Decimal("1e12"), "price": Decimal("1e14"),
             "weight_kg": Decimal("1e11"), "digging_depth_m": Decimal("1e9")}
_CONTROLLED = {
    "machine_family": {"hydraulic_excavator", "other_excavation_system"},
    "undercarriage": {"crawler", "wheeled", "special"},
    "boom_configuration": {"standard", "two_piece", "straight", "demolition_high_reach", "long_reach", "articulated", "other"},
    "stick_configuration": {"standard", "short", "long", "telescopic", "other"},
    "size_class": {"mini", "small", "medium", "large", "mining"},
    "application": {"general_excavation", "long_reach", "demolition", "material_handling", "forestry", "other"},
    "preservation_condition": {"excellent", "good", "acceptable", "poor"},
    "power_type": {"net", "gross", "rated", "other"},
    "hours_basis": {"hourmeter", "owner_declared", "documented"},
}

# Public contract for services/forms.  Values are intentionally additive; the
# long-standing textual technical fields remain the editable source of truth.
STRUCTURED_INPUT_FIELDS = frozenset({
    "variant", "machine_family", "undercarriage", "boom_configuration",
    "stick_configuration", "size_class", "application", "location_country",
    "location_region", "location_city", "depth_configuration", "power_type",
    "hours_basis", "hours_recorded_at", "estimated_year_from",
    "estimated_year_to", "preservation_condition",
})
STRUCTURED_READ_FIELDS = frozenset({
    "weight_kg", "digging_depth_m", "power_kw", "capacity_m3", "hours",
    "year", "estimated_year_from", "estimated_year_to", "price", "currency",
    *STRUCTURED_INPUT_FIELDS,
})


def _blank(value):
    return value is None or value == ""


def parse_decimal(value):
    """Parse only unambiguous decimal input; 1,500 and 1.500 are rejected."""
    if isinstance(value, bool) or _blank(value):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else None
    text = str(value).strip().replace(" ", "")
    if not _DECIMAL.fullmatch(text):
        return None
    # A lone separator followed by exactly three digits is locale-ambiguous.
    if text.count(",") + text.count(".") == 1 and len(re.split("[,.]", text)[1]) == 3:
        return None
    try:
        parsed = Decimal(text.replace(",", "."))
        return parsed if parsed.is_finite() else None
    except InvalidOperation:
        return None


def _measure(value, units):
    # A bare number in a legacy text field has no safely knowable unit.
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return None
    raw = str(value or "").replace("\u00a0", " ")
    # Spaces are a common thousands separator in equipment sheets. Remove them
    # only between digits; decimal comma/dot ambiguity is still handled by
    # parse_decimal below.
    raw = re.sub(r"(?<=\d)\s+(?=\d)", "", raw)
    match = _MEASURE.fullmatch(raw)
    if not match:
        return None
    amount = parse_decimal(match.group(1))
    unit = match.group(2).casefold().replace("³", "3")
    factor = units.get(unit)
    return amount * factor if amount is not None and factor is not None else None


def _clean_text(value, limit=180):
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] if value else None


def _year(value):
    number = parse_decimal(value)
    if number is None or number != number.to_integral_value() or not 1800 <= number <= MAX_YEAR:
        return None
    return int(number)


def _source(data):
    return data.get("data", data) if isinstance(data, dict) else {}


def normalize_structured_data(data, category=None, strict=False):
    """Return canonical numeric units and controlled values for one data payload.

    ``strict`` raises field-specific ValidationError values for supplied invalid
    data.  Normal mode is intentionally lossy: invalid or ambiguous entries are
    represented as ``None`` and cannot become searchable values.
    """
    source = _source(data)
    if not isinstance(source, dict):
        raise ValidationError("Los datos de maquinaria deben ser un objeto.")
    result = {
        "variant": _clean_text(source.get("variant")),
        "machine_family": _controlled(source, "machine_family"),
        "undercarriage": _controlled(source, "undercarriage"),
        "boom_configuration": _controlled(source, "boom_configuration"),
        "stick_configuration": _controlled(source, "stick_configuration"),
        "size_class": _controlled(source, "size_class"),
        "application": _controlled(source, "application"),
        "hours": parse_decimal(source.get("hours")),
        "hours_basis": _controlled(source, "hours_basis"),
        "hours_recorded_at": _date(source.get("hours_recorded_at")),
        "year": _year(source.get("year")),
        "estimated_year_from": _year(source.get("estimated_year_from")),
        "estimated_year_to": _year(source.get("estimated_year_to")),
        "price": parse_decimal(source.get("price")),
        "currency": _currency(source.get("currency")),
        "weight_kg": _measure(source.get("weight"), {"kg": Decimal("1"), "t": Decimal("1000"), "ton": Decimal("1000"), "tons": Decimal("1000"), "lb": Decimal("0.45359237"), "lbs": Decimal("0.45359237")}),
        "digging_depth_m": _measure(source.get("digging_depth"), {"m": Decimal("1"), "cm": Decimal("0.01"), "mm": Decimal("0.001"), "ft": Decimal("0.3048"), "in": Decimal("0.0254")}),
        "power_kw": _measure(source.get("power"), {"kw": Decimal("1"), "hp": Decimal("0.745699872"), "cv": Decimal("0.73549875")}),
        "capacity_m3": _measure(source.get("capacity"), {"m3": Decimal("1"), "l": Decimal("0.001"), "lt": Decimal("0.001"), "yd3": Decimal("0.764554858")}),
        "power_type": _controlled(source, "power_type"),
        "depth_configuration": _clean_text(source.get("depth_configuration")),
        "location_country": _clean_text(source.get("location_country"), 80),
        "location_region": _clean_text(source.get("location_region"), 120),
        "location_city": _clean_text(source.get("location_city"), 120),
        "preservation_condition": _preservation(source.get("preservation_condition")),
    }
    _validate_normalized(source, result, strict)
    return result


def _controlled(source, key):
    value = source.get(key)
    return value if value in _CONTROLLED[key] else None


def _preservation(value):
    aliases = {"excelente": "excellent", "buena": "good", "bueno": "good",
               "aceptable": "acceptable", "deficiente": "poor", "poor": "poor",
               "por confirmar": None, "": None}
    if isinstance(value, str):
        return aliases.get(value.strip().casefold(), value if value in _CONTROLLED["preservation_condition"] else None)
    return None


def _currency(value):
    value = str(value or "").strip().upper()
    return value if _CURRENCY.fullmatch(value) else None


def _date(value):
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _validate_normalized(source, result, strict):
    errors = {}
    for key in ("hours", "price", "weight_kg", "digging_depth_m", "power_kw", "capacity_m3"):
        if result[key] is not None and result[key] < 0:
            errors[key] = "Debe ser un valor no negativo."
    for key, maximum in _MAXIMUMS.items():
        if result[key] is not None and result[key] >= maximum:
            errors[key] = "El valor excede el límite admitido para una columna numérica."
    start, end = result["estimated_year_from"], result["estimated_year_to"]
    if start is not None and end is not None and start > end:
        errors["estimated_year_to"] = "El final del intervalo no puede ser anterior al inicio."
    if result["price"] is not None and not result["currency"]:
        errors["currency"] = "Indica una moneda ISO de tres letras para el precio."
    if strict:
        # Existing listings use free-text technical values (for example
        # ``4.8 kW / 6.5 HP``). They remain valid legacy content even when no
        # single canonical number can be projected; ambiguous values are simply
        # absent from numeric search instead of being guessed or rejected.
        for key, choices in _CONTROLLED.items():
            if key == "preservation_condition":
                # The existing visual checklist uses this explicit unknown
                # state. It is valid editable data but intentionally projects
                # to null, never a made-up conservation grade.
                if (not _blank(source.get(key)) and str(source.get(key)).strip().casefold() != "por confirmar"
                        and _preservation(source.get(key)) is None):
                    errors.setdefault(key, "Valor no permitido para esta clasificación.")
                continue
            if not _blank(source.get(key)) and source[key] not in choices:
                errors.setdefault(key, "Valor no permitido para esta clasificación.")
        for key in ("year", "estimated_year_from", "estimated_year_to"):
            if not _blank(source.get(key)) and result[key] is None:
                errors.setdefault(key, "Indica un año entero entre 1800 y 2200.")
        if not _blank(source.get("hours_recorded_at")) and result["hours_recorded_at"] is None:
            errors.setdefault("hours_recorded_at", "Usa fecha ISO AAAA-MM-DD.")
    if not strict:
        # A malformed historical value must never break rendering, migration or
        # snapshot creation. Its canonical projection stays absent.
        for key in ("hours", "price", "weight_kg", "digging_depth_m", "power_kw", "capacity_m3"):
            if result[key] is not None and (result[key] < 0 or (key in _MAXIMUMS and result[key] >= _MAXIMUMS[key])):
                result[key] = None
        if start is not None and end is not None and start > end:
            result["estimated_year_from"] = result["estimated_year_to"] = None
        return
    # Currency may be missing from an older partial draft. It means the price
    # cannot be indexed, not that unrelated edits are invalid.
    errors.pop("currency", None)
    if errors:
        raise ValidationError(errors)


def validate_manual_data(data, category=None):
    """Validate a user-editable payload without persisting a second data shape."""
    return normalize_structured_data(data, category, strict=True)


def structured_snapshot(data, category=None):
    """The read model persisted under a version snapshot's ``structured`` key."""
    value = normalize_structured_data(data, category, strict=False)
    # JSONField does not serialize Decimal. Floats retain numeric semantics for
    # the read model; typed indexed columns retain Decimal precision.
    return {key: float(item) if isinstance(item, Decimal) else item for key, item in value.items()}


def version_search_fields(data, category=None, provenance=None):
    """Map a snapshot or raw data dict to MachineVersion's indexed columns."""
    source = _source(data)
    normalized = normalize_structured_data(source, category, strict=False)
    if provenance is None and isinstance(data, dict):
        provenance = data.get("provenance")
    price_meta = provenance.get("price", {}) if isinstance(provenance, dict) else {}
    # A valuation is a private estimate until a person confirms it.  Older
    # snapshots without provenance retain their declared price for compatibility.
    price = normalized["price"]
    if isinstance(price_meta, dict) and price_meta.get("source") == "valuation" and price_meta.get("review") != "confirmed":
        price = None
    if price is not None and not normalized["currency"]:
        price = None
    return {
        "category": category if getattr(category, "pk", None) else None,
        "brand": _clean_text(source.get("brand"), 100) or "",
        "model": _clean_text(source.get("model"), 100) or "",
        "variant": normalized["variant"] or "",
        "undercarriage": normalized["undercarriage"] or "",
        "hours": normalized["hours"],
        "year": normalized["year"],
        "estimated_year_from": normalized["estimated_year_from"],
        "estimated_year_to": normalized["estimated_year_to"],
        "price": price,
        "currency": normalized["currency"] if price is not None and normalized["currency"] else "",
        "weight_kg": normalized["weight_kg"],
        "digging_depth_m": normalized["digging_depth_m"],
        "location_country": normalized["location_country"] or "",
        "location_region": normalized["location_region"] or "",
        "location_city": normalized["location_city"] or "",
        "preservation_condition": normalized["preservation_condition"] or "",
    }
