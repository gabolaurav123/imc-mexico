"""General reading aids, not additional specifications of a particular machine.

Primary manufacturer references reviewed 2026-09-16. No runtime web request,
database lookup, numeric conversion, or model inference is performed here.
"""
import math
import re
import unicodedata
from textwrap import wrap

from .category_profiles import capacity_label


_EMPTY_COPY = {
    "n/a", "na", "n.d.", "nd", "n/d", "unknown", "desconocido", "desconocida",
    "por definir", "pendiente", "sin información", "sin informacion", "sin datos",
    "no indicado", "no indicada", "no identificado", "no identificada", "por confirmar",
    "por revisar", "pendiente de confirmar", "sin estimar", "consultar precio", "-", "—",
}
_WORKFLOW_COPY = re.compile(
    r"\b(?:pendientes?(?:\s+de\s+(?:confirmaci[oó]n|confirmar|revisi[oó]n|revisar|validaci[oó]n))?"
    r"|por\s+(?:confirmar|revisar|definir)|sin\s+estimar)\b", re.I,
)
_SUMMARY_FIELDS = (
    ("power", "Potencia"), ("weight", "Peso operativo"), ("capacity", "Capacidad"),
    ("digging_depth", "Profundidad de excavación"), ("lift_height", "Altura de elevación"),
    ("working_height", "Altura de trabajo"), ("drum_width", "Ancho de tambor"),
    ("engine", "Motor"), ("fuel", "Combustible"), ("dimensions", "Dimensiones"),
    ("transmission", "Transmisión"), ("hydraulic_system", "Sistema hidráulico"),
    ("vibration_frequency", "Frecuencia de vibración"), ("centrifugal_force", "Fuerza centrífuga"),
)


def clean_sheet_text(value):
    """Remove empty/status-only copy without inventing a replacement value.

    Keep sentences describing real machine defects. A sentence containing an
    unresolved claim is omitted in full, never rewritten as a confirmed fact.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    text = str(value).strip()
    if text.casefold() in _EMPTY_COPY or text.casefold().strip(" .:;") in _EMPTY_COPY:
        return ""
    if not _WORKFLOW_COPY.search(text):
        return text
    parts = re.split(r"(?<=[.!?;])\s+|[\r\n]+", text)
    return " ".join(part.strip() for part in parts
                     if part.strip() and not _WORKFLOW_COPY.search(part))


def finished_sheet_data(data):
    """Clean a display copy; the editable draft and source evidence stay intact."""
    if not isinstance(data, dict):
        return {}
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            value = clean_sheet_text(value)
        if value not in (None, "") and not isinstance(value, (bool, dict, list)):
            if not isinstance(value, float) or math.isfinite(value):
                result[key] = value
    return result


def build_technical_summary(data, provenance=None, *, category=None):
    """Use the prepared AI description, or existing specs, in at most four lines.

    This presentation fallback performs no inference. It never pads missing
    facts, copies serials/contact into the summary, or mutates the saved data.
    """
    if not isinstance(data, dict):
        return []
    identifiers = [_identifier_key(data.get(key)) for key in ("serial", "vin")]

    def safe_text(value):
        text = clean_sheet_text(value)
        if any(identifier and identifier in _identifier_key(text) for identifier in identifiers):
            return ""
        return text

    description = safe_text(data.get("description"))
    paragraphs = [part.strip() for part in re.split(r"(?<=[.!?;])\s+|[\r\n]+", description) if part.strip()]
    paragraphs.extend(f"{capacity_label(category) if key == 'capacity' else label}: {value}" for key, label in _SUMMARY_FIELDS
                      if (value := safe_text(data.get(key))) and value.casefold() not in description.casefold())
    lines = []
    for paragraph in paragraphs:
        # Match the AI reference line limit so its heading and three accepted
        # features fit without dropping the last feature from the web or PDF.
        lines.extend(wrap(paragraph, width=150, break_long_words=False, break_on_hyphens=False))
        if len(lines) >= 4:
            break
    return lines[:4]


WACKER_REFERENCE = {
    "title": "Wacker Neuson · guía de magnitudes técnicas (referencia general)",
    "url": "https://cdn.mediapool.wackerneusongroup.com/asset/491085414967/document_rfl1tjoc6h2in3n9glg6hf8g33",
}
HUSQVARNA_REFERENCE = {
    "title": "Husqvarna · manual de placas compactadoras (referencia general)",
    "url": "https://www.husqvarnaconstruction.com/hcp/tdrdownload/pub000105444/doc000262673/879569062?httproute=True",
}

# The manufacturer's examples support the meaning of these headings only.
# None of their model values, applications or equipment options are imported.
READING_AIDS = (
    ("power", "Potencia", "Expresa la potencia indicada del conjunto motriz. kW y HP son unidades de potencia; este dato por sí solo no determina el consumo de combustible ni la producción por hora.", WACKER_REFERENCE),
    ("weight", "Peso", "Describe la masa declarada del equipo. Para comparar, distingue peso neto y peso operativo: accesorios, líquidos o baterías pueden cambiar la configuración incluida.", HUSQVARNA_REFERENCE),
    ("vibration_frequency", "Frecuencia de vibración", "Indica el ritmo de vibración: VPM significa vibraciones por minuto y Hz, ciclos por segundo. Se expresa por separado de la velocidad de desplazamiento.", WACKER_REFERENCE),
    ("centrifugal_force", "Fuerza centrífuga", "Describe la fuerza dinámica del mecanismo vibratorio, habitualmente expresada en kN. Es una magnitud distinta del peso del equipo y de su frecuencia de vibración.", HUSQVARNA_REFERENCE),
    ("compaction_depth", "Profundidad de compactación", "Es la profundidad declarada para la compactación. Para interpretarla hace falta el material y las condiciones indicadas en el manual del modelo; la cifra sola no acredita un resultado en obra.", HUSQVARNA_REFERENCE),
    ("capacity", "Capacidad", "La unidad y el componente determinan qué cantidad se expresa: volumen, masa o producción. Una capacidad de depósito no equivale a la capacidad de trabajo del equipo.", WACKER_REFERENCE),
    ("dimensions", "Dimensiones", "Permiten leer el tamaño declarado. Comprueba el orden de las medidas y si corresponden al equipo completo, a su base o a una configuración plegada.", HUSQVARNA_REFERENCE),
)


def _identifier_key(value):
    return "".join(char for char in unicodedata.normalize("NFKC", str(value or "")).casefold() if char.isalnum())


def _display_value(value, private_identifiers):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    text = str(value).strip()
    if (not text or len(text) > 160 or not re.search(r"\d", text)
            or re.search(r"[<>@\x00-\x1f\x7f]|https?://|www\.", text, re.I)):
        return None
    key = _identifier_key(text)
    if any(identifier and identifier in key for identifier in private_identifiers):
        return None
    return text


def _reading_status(meta):
    if not isinstance(meta, dict):
        return "Dato de la ficha"
    if meta.get("review") == "confirmed":
        return "Confirmado por el anunciante"
    if meta.get("review_reason") == "conflicting_reading":
        return "Lectura en conflicto · por revisar"
    if meta.get("source") == "user":
        return "Declarado por el anunciante"
    if meta.get("source") == "web":
        return "Referencia web · por revisar"
    if meta.get("review") == "clear" and meta.get("source") in {"plate", "image"}:
        return "Leído en placa" if meta["source"] == "plate" else "Leído en fotografía"
    if meta:
        return "Dato por revisar"
    return "Dato de la ficha"


def build_sheet_details(data, provenance=None, *, category=None):
    """Return at most seven factual aids for values already present in this view.

    Pass approved snapshot data for a public/versioned view. Private keys,
    evidence, asset/job IDs and user-supplied source URLs are never returned.
    The result does not mutate data or provenance and cannot complete blanks.
    """
    if not isinstance(data, dict):
        return []
    provenance = provenance if isinstance(provenance, dict) else {}
    # These documents describe compactors only. An unknown category or a
    # forklift must never acquire a compactor reference merely by having weight.
    compaction_category = _identifier_key(category) in {
        "compactador", "compactadores", "compactadora", "compactadoras",
        "placacompactadora", "placascompactadoras", "vibrocompactador", "vibrocompactadores",
    }
    private_identifiers = [_identifier_key(data.get(key)) for key in ("serial", "vin")]
    items = []
    for key, label, explanation, reference in READING_AIDS:
        value = _display_value(data.get(key), private_identifiers)
        if value is None:
            continue
        items.append({"key": key, "label": label, "value": value, "explanation": explanation,
                      "reading_status": _reading_status(provenance.get(key)),
                      "reference": dict(reference) if compaction_category else {}, "scope": "general_context"})
    return items
