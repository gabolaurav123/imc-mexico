"""Shared input checks for normal and session-bound preparation routes."""
import re
from copy import deepcopy

from django.core.exceptions import ValidationError

from .models import AnalysisJob


def contact_complete(user):
    from .forms import COUNTRY_PREFIXES, _split_phone
    prefix, national = _split_phone(user.phone)
    return bool(user.email and prefix in COUNTRY_PREFIXES and re.fullmatch(r"[0-9]{4,14}", national)
                and len(prefix + national) <= 16 and user.contact_preference in {"email", "call", "whatsapp"})


def preparation_mode(machine, asset_ids=None):
    """Choose a supported preparation route without treating model data as unit proof."""
    images = machine.assets.filter(kind="image", processing_status="ready").exclude(purpose="document")
    if asset_ids:
        if not isinstance(asset_ids, list):
            raise ValidationError("Selecciona fotografías válidas de esta maquinaria.")
        images = images.filter(pk__in=asset_ids)
    if images.exists():
        return "analysis"
    serial = str(machine.data.get("serial") or "").strip()
    if len(re.sub(r"[^A-Za-z0-9]", "", serial)) < 3:
        from .catalogue_intake import catalogue_reference_ready
        if catalogue_reference_ready(machine):
            return "catalogue"
        raise ValidationError("Escribe el número de serie o sube al menos una fotografía de la máquina para generar su ficha.")
    return "description"


def catalogue_enrichment_needed(machine):
    """Whether an approved catalogue choice still lacks model references.

    This is deliberately about the model fiche, not facts of the particular
    machine: unit-only values remain outside this no-photo route.  A complete
    local period, market range, and at least one technical model value needs no
    remote work and should retain the instant catalogue response.
    """
    from .catalogue_intake import catalogue_reference_ready
    if not catalogue_reference_ready(machine):
        return False
    data, provenance = machine.data, machine.provenance
    has_period = all(data.get(key) not in (None, "") for key in
                     ("estimated_year_from", "estimated_year_to"))
    has_market = all(data.get(key) not in (None, "") for key in
                     ("estimate_min", "estimate_max", "estimate_currency"))
    technical = {"power", "weight", "capacity", "dimensions", "fuel", "engine", "transmission",
                 "digging_depth", "hydraulic_system", "working_width", "lift_height", "voltage"}
    has_technical_reference = any(data.get(key) not in (None, "")
                                  and isinstance(provenance.get(key), dict)
                                  and provenance[key].get("scope") == "model"
                                  for key in technical)
    return not (has_period and has_market and has_technical_reference)


def has_completed_preparation(machine):
    from .catalogue_intake import catalogue_reference_ready, catalogue_reference_stale
    if catalogue_reference_stale(machine):
        return False
    if not any(machine.data.get(key) for key in ("brand", "model", "description")):
        return False
    current_photo_ids = {str(pk) for pk in machine.assets.filter(kind="image", processing_status="ready")
                         .exclude(purpose="document").values_list("pk", flat=True)}
    def valid_normal_job(job):
        result = job.result if isinstance(job.result, dict) else {}
        if result.get("preflight") is True:
            return False
        consistency = result.get("consistency")
        if result.get("blocking_reason") or isinstance(consistency, dict) and consistency.get("status") == "contradiction":
            return False
        relevance = result.get("relevance")
        relevance = relevance if isinstance(relevance, dict) else {}
        return relevance.get("status") not in {"unrelated", "uncertain"}
    if not current_photo_ids:
        if catalogue_reference_ready(machine):
            return True
        return any(valid_normal_job(job) for job in machine.analysis_jobs.filter(status="completed"))
    prepared_photo_ids = set()
    for job in machine.analysis_jobs.filter(status="completed", mode="analysis"):
        if not valid_normal_job(job):
            continue
        prepared_photo_ids.update(str(asset_id) for asset_id in job.asset_ids)
    return current_photo_ids <= prepared_photo_ids


def preparation_completeness(machine, job=None):
    """Check the saved sheet, including edits made while a new AI job ran.

    Historical shares keep their contract. New jobs explicitly declare this
    completion contract, so unavailable evidence cannot silently mean ready.
    """
    if job is None:
        # A photo check does not generate a sheet or replace its completion
        # contract. A later preflight must not make missing fields disappear.
        job = next((candidate for candidate in machine.analysis_jobs.filter(status="completed")
                    .order_by("-created_at", "-pk").iterator()
                    if not (isinstance(candidate.result, dict) and candidate.result.get("preflight") is True)), None)
    if not job or not isinstance(job.result, dict) or "completion" not in job.result:
        return {}
    from .public_data import public_projection
    from .description_quality import has_technical_description
    from .technical_description import recovered_technical_description
    from .structured_data import has_valid_year_or_range
    category = machine._state.fields_cache.get("category")
    if category is None and machine.category_id and not machine._state.adding:
        category = machine.category
    category_name = category.name if category else None
    data = public_projection({"data": machine.data, "provenance": machine.provenance,
                              "category_name": category_name})
    missing = [key for key in ("brand", "model") if not data.get(key)]
    if not machine.category_id:
        missing.append("category")
    if not has_valid_year_or_range(data):
        missing.append("year_range")
    if not all(data.get(key) is not None for key in ("estimate_min", "estimate_max", "estimate_currency")):
        missing.append("price_range")
    recovered = recovered_technical_description(machine.data, machine.provenance, category=category_name)
    if not (has_technical_description(data.get("description"), machine.provenance.get("description"))
            or recovered and data.get("description") == recovered):
        missing.append("description")
    labels = {"brand": "marca", "model": "modelo", "category": "tipo de máquina",
              "year_range": "rango de años", "price_range": "rango de precio", "description": "características técnicas"}
    message = ("No se pudo completar: " + ", ".join(labels[key] for key in missing)
               + ". Agrega una foto nítida de la placa o corrige la marca y el modelo y vuelve a generar la ficha.") if missing else ""
    return {"missing_fields": missing, "message": message}


def require_prepared_serial(machine):
    serial = str(machine.data.get("serial") or "").strip()
    from .catalogue_intake import catalogue_reference_ready
    if catalogue_reference_ready(machine):
        return "catalogue"
    if not machine.category_id or len(re.sub(r"[^A-Za-z0-9]", "", serial)) < 3:
        raise ValidationError("Agrega una fotografía del equipo o su número de serie y selecciona el tipo de máquina.")
    if not has_completed_preparation(machine):
        raise ValidationError("Genera la ficha con el número de serie antes de enviarla a revisión, o agrega una fotografía del equipo.")


def assessed_photo_states(machine):
    """Latest per-photo decisions; a later unrelated photo cannot hide an older one."""
    states = {}
    for job in machine.analysis_jobs.filter(status="completed", mode="analysis").order_by("-created_at", "-pk"):
        result = job.result if isinstance(job.result, dict) else {}
        relevance = result.get("relevance", {})
        if not isinstance(relevance, dict):
            continue
        for key, state in (("excluded_asset_ids", "unrelated"), ("uncertain_asset_ids", "uncertain"),
                           ("accepted_asset_ids", "accepted")):
            values = relevance.get(key, [])
            for value in values if isinstance(values, list) else []:
                states.setdefault(str(value), state)
    return states


def require_consistent_photos(machine, asset_ids=None):
    """Restrict this fiche, not the account, when actual photo evidence conflicts."""
    purposes = {str(pk): purpose for pk, purpose in machine.assets.filter(kind="image", processing_status="ready")
                .exclude(purpose="document").values_list("pk", "purpose")}
    ids = set(purposes)
    if asset_ids is not None:
        ids &= {str(value) for value in asset_ids}
    states = assessed_photo_states(machine)
    if any(states.get(pk) == "unrelated" for pk in ids):
        raise ValidationError("Retira las fotografías que no corresponden a maquinaria antes de compartir o enviar esta ficha.")
    from .analysis_specialization import check_equipment_consistency, historical_model_fragments, private_consistency_error
    # Recompare the latest readable evidence with current owner corrections.
    # A human correction can resolve a conflict without suspending the person.
    seen = set()
    snapshot = {"data": machine.data, "provenance": machine.provenance,
        "category": machine.category.name if machine.category_id else "", "revision": machine.revision}
    model_fragments = set()
    model_diagnostics = {}
    combined = {"fields": [], "image_observations": []}
    for job in AnalysisJob.objects.filter(machine=machine, status="completed", mode="analysis").order_by("-created_at", "-pk"):
        if not isinstance(job.result, dict):
            continue
        relevant = (set(map(str, job.asset_ids)) & ids) - seen
        if not relevant:
            continue
        seen |= relevant
        result = deepcopy(job.result)
        result["fields"] = [field for field in result.get("fields", []) if str(field.get("asset_id")) in relevant]
        result["image_observations"] = [item for item in result.get("image_observations", []) if str(item.get("asset_id")) in relevant]
        model_fragments.update(historical_model_fragments(result, snapshot,
            {pk for pk in relevant if purposes[pk] == "general"}, diagnostics=model_diagnostics))
        combined["fields"].extend(result["fields"])
        combined["image_observations"].extend(result["image_observations"])
    # Photos analysed in separate jobs still belong to one fiche. Compare their
    # latest readable evidence together, not only within individual jobs.
    combined["category"] = next((item.get("category") for item in combined["image_observations"] if item.get("category")), None)
    check_equipment_consistency(combined, snapshot, model_fragments=model_fragments)
    if combined.get("consistency", {}).get("status") == "contradiction":
        raise ValidationError(private_consistency_error(combined, model_diagnostics))
