"""General reading aids, not additional specifications of a particular machine.

Primary manufacturer references reviewed 2026-09-16. No runtime web request,
database lookup, numeric conversion, or model inference is performed here.
"""
import math
import re
import unicodedata


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


def build_sheet_details(data, provenance=None):
    """Return at most seven factual aids for values already present in this view.

    Pass approved snapshot data for a public/versioned view. Private keys,
    evidence, asset/job IDs and user-supplied source URLs are never returned.
    The result does not mutate data or provenance and cannot complete blanks.
    """
    if not isinstance(data, dict):
        return []
    provenance = provenance if isinstance(provenance, dict) else {}
    private_identifiers = [_identifier_key(data.get(key)) for key in ("serial", "vin")]
    items = []
    for key, label, explanation, reference in READING_AIDS:
        value = _display_value(data.get(key), private_identifiers)
        if value is None:
            continue
        items.append({"key": key, "label": label, "value": value, "explanation": explanation,
                      "reading_status": _reading_status(provenance.get(key)),
                      "reference": dict(reference), "scope": "general_context"})
    return items
