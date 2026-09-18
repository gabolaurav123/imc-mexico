"""Small, conservative projection helpers for public sheets and exports.

Public responses are an allowlist.  Internal provenance, plate material,
valuation comparables, and placeholder prose never cross this boundary.
"""
from copy import deepcopy


PUBLIC_KEYS = frozenset({
    "brand", "model", "variant", "year", "estimated_year_from", "estimated_year_to",
    "hours", "undercarriage", "power", "weight", "weight_kg", "capacity",
    "digging_depth", "digging_depth_m", "location", "location_country",
    "location_region", "location_city", "country_of_origin", "condition",
    "preservation_condition", "preservation_notes", "usage_condition", "operating_status", "visible_defects",
    "visible_components", "attachments", "applications", "description", "title",
    "price", "currency", "availability", "kilometers", "voltage", "lift_height", "load_center",
    "battery_weight", "battery_capacity", "fork_length", "front_tire_size", "rear_tire_size",
    "mast_tilt", "load_tire_tread", "manufacturer", "manufacturer_address", "fuel",
    "hydraulic_system", "dimensions", "transmission", "engine", "power", "capacity",
    "vibration_frequency", "centrifugal_force", "compaction_depth", "country_of_origin",
    "machine_family", "boom_configuration", "stick_configuration", "size_class",
    "application", "power_type", "depth_configuration",
})
PRIVATE_KEYS = frozenset({
    "serial", "vin", "plate_transcription", "plate_kind", "plate_type", "no_plate",
    "notes", "document", "owner_email", "owner_phone", "email", "phone",
    "contact_public", "research", "web_research", "provenance", "valuation",
    "comparables", "sources", "internal_messages", "estimate_basis", "estimate_missing_info",
})
PLACEHOLDERS = {"n/a", "na", "n.d.", "nd", "por definir", "pendiente", "sin información",
                "sin informacion", "desconocido", "no indicado", "no identificada", "por confirmar",
                "no identificado", "no indicada", "pendiente de confirmar", "sin datos", "sin estimar", "n/d", "consultar precio", "-", "—"}


def _present(value):
    if value is None or value is False or isinstance(value, (dict, list)):
        return False
    text = str(value).strip()
    return bool(text) and text.casefold() not in PLACEHOLDERS


def _identifier_key(value):
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def public_projection(snapshot):
    """Return only publishable, non-empty values from an approved snapshot."""
    root = snapshot if isinstance(snapshot, dict) else {}
    raw = root.get("data", root)
    if not isinstance(raw, dict):
        return {}
    identifiers = {_identifier_key(raw.get(key)) for key in ("serial", "vin") if _identifier_key(raw.get(key))}
    result = {}
    provenance = root.get("provenance", {}) if isinstance(root.get("provenance", {}), dict) else {}
    for key, value in deepcopy(raw).items():
        if key in PRIVATE_KEYS or key not in PUBLIC_KEYS or not _present(value):
            continue
        if identifiers and any(identifier in _identifier_key(value) for identifier in identifiers):
            continue
        # A valuation proposal is not the advertiser's asking price.  Legacy
        # snapshots may contain it in ``price``; only an explicit confirmation
        # is publishable.
        meta = provenance.get(key, {})
        if key == "price" and isinstance(meta, dict) and meta.get("source") == "valuation" and meta.get("review") != "confirmed":
            continue
        result[key] = value
    # Keep approximate age explicitly approximate; never manufacture an exact year.
    if "year" in result and result["year"] in ("", None):
        result.pop("year", None)
    # Monetary values are meaningful only with an explicit ISO currency.
    if "price" in result and not _present(result.get("currency")):
        result.pop("price", None)
    if "price" not in result:
        result.pop("currency", None)
    return result


def public_json(snapshot, *, title=None, category=None, availability=None):
    data = public_projection(snapshot)
    root = snapshot if isinstance(snapshot, dict) else {}
    raw = root.get("data", root) if isinstance(root, dict) else {}
    identifiers = {_identifier_key(raw.get(key)) for key in ("serial", "vin") if _identifier_key(raw.get(key))}
    snapshot_title = root.get("title") if isinstance(root, dict) else None
    safe_title = title if _present(title) else snapshot_title if _present(snapshot_title) else data.get("title")
    if identifiers and any(identifier in _identifier_key(safe_title) for identifier in identifiers):
        safe_title = None
    from .structured_data import structured_snapshot
    structured = {key: value for key, value in structured_snapshot(data, None).items()
                  if value not in (None, "", [])}
    return {
        "schema_version": "public-machine-v1",
        "title": safe_title,
        "category": category if _present(category) else None,
        "availability": availability if _present(availability) else None,
        "data": data,
        "structured": structured,
    }
