"""Recover concise prose from current accepted facts without another AI call.

This is a read-only projection, never a new fact or a saved owner correction.
Recomputing from current values keeps deletions, conflicts and edits effective.
"""
import re

from .category_profiles import capacity_label
from .description_quality import has_technical_description


_FIELDS = (
    "weight", "capacity", "power", "digging_depth", "lift_height", "platform_height",
    "gradeability", "working_width", "horizontal_outreach", "voltage", "dimensions",
    "maximum_reach_ground", "drum_width", "vibration_frequency", "centrifugal_force",
    "compaction_depth", "hydraulic_flow", "travel_speed", "blade_width",
)
_AUTOMATIC = {"system", "image", "plate", "visual_proposal", "ai_reference", "web"}


def recovered_technical_description(data, provenance=None, *, category=None):
    """Return three or four literal technical facts, or no replacement at all.

    Identity, age and price never count as technical features. Unconfirmed web
    proposals and unclear/conflicting readings cannot supply this fallback.
    """
    if not isinstance(data, dict):
        return ""
    provenance = provenance if isinstance(provenance, dict) else {}
    description_meta = provenance.get("description", {})
    description_meta = description_meta if isinstance(description_meta, dict) else {}
    description = data.get("description")
    if (description_meta.get("source") == "user" or description_meta.get("review") == "confirmed"
            or has_technical_description(description, description_meta)
            or description and description_meta.get("source") not in _AUTOMATIC):
        return ""

    from .research import LABELS, identifier_key
    from .research_field_values import is_valid_research_field_value
    from .sheet_details import clean_sheet_text
    identifiers = {identifier_key(data.get(key)) for key in ("serial", "vin")}
    identifiers.update(identifier_key(meta.get("matched_serial")) for meta in provenance.values()
                       if isinstance(meta, dict))
    identifiers.discard("")
    lines = []
    for key in _FIELDS:
        meta = provenance.get(key, {})
        if not isinstance(meta, dict) or meta.get("review_reason") == "conflicting_reading":
            continue
        source, review = meta.get("source"), meta.get("review")
        if source in {"image", "plate"} and review == "clear" and meta.get("component") == "machine":
            origin = "según la placa" if source == "plate" else "según la fotografía"
        elif source == "user" or review == "confirmed":
            origin = "declarado en la ficha"
        else:
            continue
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        literal = str(value).strip()
        if (not re.search(r"\d", literal) or clean_sheet_text(literal) != literal
                or re.search(r"https?://|www\.|@|[<>\x00-\x1f\x7f]", literal, re.I)
                or any(identifier in identifier_key(literal) for identifier in identifiers)
                or not is_valid_research_field_value(key, literal)):
            continue
        label = capacity_label(category) if key == "capacity" else LABELS[key]
        # Fixed wording carries provenance without exposing raw evidence or
        # promoting a catalog value to a specification of this particular unit.
        if source == "web":
            line = f"Valor de {label.lower()} de referencia del modelo: {literal}"
        elif origin == "declarado en la ficha":
            line = f"Valor de {label.lower()} declarado en la ficha: {literal}"
        else:
            line = f"{label} {origin}: {literal}"
        if not line.endswith((".", "!", "?", "…")):
            line += "."
        if len(line) > 150:
            continue
        lines.append(line)
        if len(lines) == 4:
            break
    text = "\n".join(lines)
    return text if len(lines) >= 3 and has_technical_description(text) else ""


def description_projection(data, provenance=None, *, category=None):
    """Copy saved data, replacing only insufficient automatic presentation text."""
    result = dict(data) if isinstance(data, dict) else {}
    recovered = recovered_technical_description(result, provenance, category=category)
    if recovered:
        result["description"] = recovered
    return result
