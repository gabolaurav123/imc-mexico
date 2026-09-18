"""Editable commercial fields, shared by intake, sheets and exports."""

VISUAL_LABELS = {
    "usage_condition": "Condición de uso aparente",
    "preservation_condition": "Conservación aparente",
    "preservation_notes": "Detalles que justifican la conservación",
    "operating_status": "Estado de funcionamiento",
    "visible_defects": "Desgaste y detalles visibles",
    "visible_components": "Componentes visibles",
    "attachments": "Accesorios visibles",
    "applications": "Aplicaciones sugeridas",
}
VISUAL_CHOICES = {
    "usage_condition": {"Aparentemente nueva", "Usada", "Por confirmar"},
    "preservation_condition": {"Excelente", "Bueno", "Aceptable", "Deficiente", "Por confirmar"},
    "operating_status": {"Pendiente de confirmar", "Confirmado por el propietario", "No funciona (declarado por el propietario)"},
}
ESTIMATE_LABELS = {
    "estimate_min": "Valor orientativo mínimo", "estimate_max": "Valor orientativo máximo",
    "estimate_suggested_price": "Precio de publicación sugerido", "estimate_date": "Fecha de estimación",
    "estimate_currency": "Moneda de referencia", "estimate_market": "Mercado de referencia",
    "estimate_basis": "Base de la estimación", "estimate_missing_info": "Qué ayudaría a estimar el precio",
}
ESTIMATE_LABEL = "Estimación orientativa, editable y sujeta a confirmación"
AGE_LABELS = {
    "estimated_year_from": "Año aproximado desde",
    "estimated_year_to": "Año aproximado hasta",
    "estimated_year_basis": "Indicios para el año aproximado",
}
AGE_LABEL = "Año aproximado · por confirmar"
VALUATION_KEYS = set(ESTIMATE_LABELS) | {"price", "currency"}


def commercial_rows(data, provenance):
    rows = []
    for key, label in VISUAL_LABELS.items():
        if data.get(key) in (None, ""):
            continue
        meta = provenance.get(key, {})
        source = "Editado en la ficha" if meta.get("source") == "user" else (
            "Pendiente de confirmación del propietario" if key == "operating_status" else "Sugerencia visual · editable")
        rows.append({"key": key, "label": label, "value": data[key], "source_label": source})
    return rows
