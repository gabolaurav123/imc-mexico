"""Presentation labels for coded values; descriptive legacy text stays intact."""
from django import template
from portal.sheet_details import build_technical_summary, finished_sheet_data

register = template.Library()


@register.filter
def finished_data(data):
    return finished_sheet_data(data)


@register.filter
def technical_summary(data):
    if isinstance(data, list):
        return data[:4]
    return build_technical_summary(data)


@register.filter
def condition_label(value):
    text = str(value or "")
    return {"new": "Nueva", "used": "Usada", "refurbished": "Reacondicionada",
            "for_repair": "Para reparación", "unknown": "Por confirmar"}.get(text.strip().casefold(), text)


@register.filter
def plate_component_label(value):
    text = str(value or "")
    return {"machine": "La máquina completa", "engine": "El motor", "transmission": "La transmisión",
            "other": "Otro componente", "unknown": "No identificado"}.get(text.strip().casefold(), text)
