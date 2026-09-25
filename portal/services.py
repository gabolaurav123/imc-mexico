"""Transactional business boundary. Views and admin must use these operations."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from string import Template
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import UUID
import ipaddress
import re
import unicodedata

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max,Q
from django.utils import timezone

from .models import (AnalysisJob, Asset, AuditEvent, Category, Consent, Machine, MachineVersion,
                     Message, Notification, NotificationTemplate, PreparedShare, Publication, Submission, User, WorkflowStatus)
from .commercial import VISUAL_LABELS, VISUAL_CHOICES, ESTIMATE_LABELS, VALUATION_KEYS, AGE_LABELS
from .analysis_specialization import EXCAVATOR_FIELDS, SPECIALIZED_FIELDS


PLATE_TECHNICAL_LABELS = {"vibration_frequency": "Frecuencia de vibración", "centrifugal_force": "Fuerza centrífuga",
                          "compaction_depth": "Profundidad de compactación", "country_of_origin": "País de fabricación",
                          "digging_depth": "Profundidad máxima de excavación", "hydraulic_system": "Sistema hidráulico",
                          "front_tire_size": "Llantas delanteras", "rear_tire_size": "Llantas traseras",
                          "mast_tilt": "Inclinación mástil (placa)", "load_tire_tread": "Entrecentros de llantas de carga",
                          "manufacturer": "Fabricante", "manufacturer_address": "Dirección del fabricante",
                          "voltage": "Voltaje", "lift_height": "Altura de elevación", "load_center": "Centro de carga",
                          "battery_weight": "Peso de batería", "battery_capacity": "Capacidad de batería", "fork_length": "Longitud de horquillas"}
PLATE_TECHNICAL_LABELS.update(working_width="Ancho de trabajo", maximum_weight="Peso operativo máximo",
                              drum_type="Tipo de tambor", emissions="Etapa de emisiones")
CATALOGUE_TECHNICAL_LABELS = {
    "engine_displacement": "Cilindrada", "boom_length": "Longitud de pluma",
    "stick_length": "Longitud de brazo", "maximum_reach_ground": "Alcance máximo a nivel de suelo",
    "maximum_loading_height": "Altura máxima de carga", "bucket_digging_force": "Fuerza de excavación del cucharón",
    "stick_digging_force": "Fuerza de excavación del brazo", "hydraulic_flow": "Caudal hidráulico",
    "swing_speed": "Velocidad de giro", "drum_width": "Ancho de tambor",
    "drum_diameter": "Diámetro de tambor", "travel_speed": "Velocidad de desplazamiento",
    "fuel_capacity": "Capacidad de combustible", "water_tank_capacity": "Capacidad de tanque de agua",
    "platform_height": "Altura de plataforma", "horizontal_outreach": "Alcance horizontal",
    "gradeability": "Pendiente superable", "swing": "Giro", "blade_width": "Ancho de hoja",
}
DATA_FIELDS = {"brand", "model", "model_family", "year", "serial", "hours", "description", "location", "price", "currency", "condition", "notes", "contact_public", "plate_transcription", "plate_type", "plate_kind", "no_plate", "kilometers", "power", "capacity", "weight", "dimensions", "fuel", "attachments", "engine", "transmission"} | PLATE_TECHNICAL_LABELS.keys()
AUTOMATIC_DATA_FIELDS = {"brand", "model", "model_family", "year", "serial", "hours", "power", "weight", "capacity",
                         "dimensions", "fuel", "kilometers", "engine", "transmission", "description"} | PLATE_TECHNICAL_LABELS.keys()
WEB_DATA_FIELDS = {"brand", "model", "power", "weight", "capacity", "dimensions", "fuel", "engine", "transmission"} | PLATE_TECHNICAL_LABELS.keys()
DATA_FIELDS |= VISUAL_LABELS.keys() | ESTIMATE_LABELS.keys() | AGE_LABELS.keys()
DATA_FIELDS |= SPECIALIZED_FIELDS
DATA_FIELDS |= CATALOGUE_TECHNICAL_LABELS.keys()
AUTOMATIC_DATA_FIELDS |= VISUAL_LABELS.keys() | VALUATION_KEYS | AGE_LABELS.keys()
AUTOMATIC_DATA_FIELDS |= EXCAVATOR_FIELDS
AUTOMATIC_DATA_FIELDS |= CATALOGUE_TECHNICAL_LABELS.keys()
WEB_DATA_FIELDS |= EXCAVATOR_FIELDS
WEB_DATA_FIELDS |= AGE_LABELS.keys()
WEB_DATA_FIELDS |= CATALOGUE_TECHNICAL_LABELS.keys()
WEB_FIELD_LABELS = {"brand": "Marca", "model": "Modelo", "power": "Potencia", "weight": "Peso",
                    "capacity": "Capacidad", "dimensions": "Dimensiones", "fuel": "Combustible",
                    "engine": "Motor", "transmission": "Transmisión", "year": "Año", **PLATE_TECHNICAL_LABELS,
                    **CATALOGUE_TECHNICAL_LABELS, **AGE_LABELS}
NUMERIC_READING_FIELDS = {"serial", "year", "hours", "kilometers", "power", "weight", "capacity", "dimensions",
                          "vibration_frequency", "centrifugal_force", "compaction_depth", "front_tire_size",
                          "rear_tire_size", "mast_tilt", "load_tire_tread", "voltage", "lift_height", "load_center",
                          "battery_weight", "battery_capacity", "fork_length", "digging_depth",
                          *CATALOGUE_TECHNICAL_LABELS.keys()}


def _same_image_numeric_conflict(machine, key, value, meta):
    previous = machine.provenance.get(key, {})
    if (key not in NUMERIC_READING_FIELDS or _human_provenance(machine, key)
            or not isinstance(previous, dict) or not previous.get("analysis_id")
            or previous.get("source") not in {"plate", "image"} or meta.get("source") not in {"plate", "image"}
            or not meta.get("asset_id") or previous.get("asset_id") != meta["asset_id"]
            or machine.data.get(key) in (None, "")
            or (previous.get("review") != "clear" and previous.get("review_reason") != "conflicting_reading")):
        return False
    def literal(text):
        return "".join(unicodedata.normalize("NFKC", str(text)).casefold().split())
    return previous.get("review_reason") == "conflicting_reading" or literal(machine.data[key]) != literal(value)


def _reference_text(value):
    value = str(value or "")
    for _ in range(3):
        value = unquote(value)
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def _public_reference_url(url, serials, *, include_private=False):
    """Keep an actual citation intact or withhold it; never invent a substitute."""
    if not isinstance(url, str) or len(url) > 2000 or any(ord(c) < 32 for c in url):
        return ""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if parsed.scheme not in {"https", "http"} or not host or parsed.username or parsed.password:
            return ""
        if host.casefold() in {"localhost", "localhost.localdomain"} or "." not in host:
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
        if not include_private and any(_reference_text(key) in {"serial", "serialnumber", "serie", "numerodeserie", "vin", "pin", "sn"}
               for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            return ""
        if not include_private and any(serial in _reference_text(url) for serial in serials):
            return ""
    except (ValueError, UnicodeError):
        return ""
    return url


def _reference_identity_matches(data, provenance, identity, scope):
    if not isinstance(identity, dict):
        return False
    for key in (("brand", "model", "serial") if scope == "exact_serial" else ("brand", "model")):
        researched = identity.get(key)
        if not researched:
            continue
        current = data.get(key)
        current_key, researched_key = _reference_text(current), _reference_text(researched)
        if key == "brand":
            aliases = {"cat": "caterpillar", "deere": "johndeere", "volvoce": "volvo"}
            current_key, researched_key = aliases.get(current_key, current_key), aliases.get(researched_key, researched_key)
        if current_key and current_key != researched_key:
            return False
        meta = provenance.get(key, {})
        if not current_key and isinstance(meta, dict) and (meta.get("source") == "user" or meta.get("review") == "confirmed"):
            return False
    return True


def public_web_references(snapshot, *, include_private=False):
    """Validated citations derived only from the displayed immutable data.

    Public callers redact unit-specific links and titles. Authenticated internal
    views may explicitly retain those URLs/titles; signature, identity and URL
    safety checks still apply. No evidence, job IDs or plate IDs are returned.
    """
    include_private = include_private is True
    data = snapshot.get("data", {})
    provenance = snapshot.get("provenance", {})
    if not isinstance(data, dict) or not isinstance(provenance, dict):
        return []
    serials = {_reference_text(data.get(key)) for key in ("serial", "vin") if data.get(key)} - {""}
    references = []
    grouped_periods = set()

    def citation_source(source, private_serials, scope):
        title = re.sub(r"[\x00-\x1f\x7f]", " ", str(source.get("source_title") or "Fuente de referencia"))[:500]
        title = " ".join(re.sub(r"<br\s*/?>", " ", title, flags=re.I).split())
        public_url = _public_reference_url(source.get("source_url"), private_serials)
        url = _public_reference_url(source.get("source_url"), private_serials, include_private=include_private)
        private_source = not public_url or any(serial in _reference_text(title) for serial in private_serials) or (scope == "exact_serial" and not private_serials)
        hidden_source = not url or (private_source and not include_private)
        return {"source_url": "" if hidden_source else url,
                "source_title": "Fuente privada" if hidden_source else title,
                "private_source": private_source}

    for key, label in WEB_FIELD_LABELS.items():
        if key in AGE_LABELS and all(data.get(bound) in (None, "") for bound in ("estimated_year_from", "estimated_year_to")):
            continue
        meta = provenance.get(key, {})
        value = data.get(key)
        if value is None or value == "" or not isinstance(value, (str, int, float)) or isinstance(value, bool):
            continue
        if not isinstance(meta, dict) or meta.get("source") != "web" or meta.get("scope") not in {"model", "exact_serial"}:
            continue
        if key == "year" and meta["scope"] != "exact_serial":
            continue
        from .research import is_validated_web_field
        manifests = snapshot.get("web_research", {})
        manifest = manifests.get(meta.get("analysis_id"), {}) if isinstance(manifests, dict) else {}
        if not is_validated_web_field({"research": manifest}, key, value, {**meta, "review": "needs_review"}):
            continue
        identity = manifest.get("identity", {})
        if not _reference_identity_matches(data, provenance, identity, meta["scope"]):
            continue
        private_serials = serials | {_reference_text(identity.get("serial")), _reference_text(meta.get("matched_serial"))} - {""}
        signed_field = next((item for item in manifest.get("fields", [])
                             if item.get("key") == key and (item.get("value") == value or
                                 key in {"year", "estimated_year_from", "estimated_year_to"}
                                 and type(value) is int and str(item.get("value")) == str(value))), {})
        if key in AGE_LABELS and signed_field.get("period_origin") == "lectura_catalogue_metadata_v1":
            analysis_id = meta.get("analysis_id")
            if analysis_id in grouped_periods:
                continue
            # Read only records covered by the manifest signature. The editable
            # provenance must never add URLs or attribute a human range to them.
            records = signed_field.get("period_records", [])
            bounds = {}
            for bound in ("estimated_year_from", "estimated_year_to"):
                bound_meta = provenance.get(bound, {})
                if (isinstance(bound_meta, dict) and bound_meta.get("analysis_id") == analysis_id
                        and data.get(bound) not in (None, "")
                        and is_validated_web_field({"research": manifest}, bound, data[bound],
                                                  {**bound_meta, "review": "needs_review"})):
                    bounds[bound] = data[bound]
            if not bounds or not isinstance(records, list) or not records:
                continue
            start, end = bounds.get("estimated_year_from"), bounds.get("estimated_year_to")
            range_value = f"{start}–{end}" if start is not None and end is not None else f"Desde {start}" if start is not None else f"Hasta {end}"
            sources = [{**citation_source(record, private_serials, "model"),
                        "period": f"{record['start_year']}–{record['end_year']}"} for record in records]
            bound_key = next(iter(bounds))
            references.append({"field": bound_key, "label": "Año aproximado · por confirmar",
                "value": bounds[bound_key], "display_value": range_value, "scope": "model",
                "scope_label": "Periodos documentados del modelo; el rango reúne estas fuentes y no confirma el año de esta unidad",
                "source_url": "", "source_title": "Referencias del periodo", "sources": sources,
                "private_source": any(source["private_source"] for source in sources),
                "review_label": "Pendiente de confirmación"})
            grouped_periods.add(analysis_id)
            continue
        references.append({"field": key, "label": label, "value": value, "scope": meta["scope"],
            "scope_label": "Referencia del modelo; confirmar en este equipo" if meta["scope"] == "model" else "Referencia de la unidad; sujeta a revisión",
            **citation_source(meta, private_serials, meta["scope"]),
            "review_label": "Confirmado por el anunciante" if meta.get("review") == "confirmed" else "Pendiente de revisión"})
    return references


def web_research_for_provenance(provenance):
    """Copy source proofs into snapshots so later job changes cannot alter citations."""
    identifiers = {meta.get("analysis_id") for meta in provenance.values()
                   if isinstance(meta, dict) and meta.get("source") == "web" and meta.get("analysis_id")}
    valid_identifiers = set()
    for value in identifiers:
        try:
            valid_identifiers.add(UUID(value))
        except (ValueError, TypeError, AttributeError):
            continue
    return {str(job.pk): deepcopy(job.result.get("research", {}))
            for job in AnalysisJob.objects.filter(pk__in=valid_identifiers) if isinstance(job.result, dict)}


def valuations_for_provenance(provenance):
    ids = set()
    for meta in provenance.values():
        if isinstance(meta, dict) and meta.get("source") == "valuation":
            try:
                ids.add(UUID(meta.get("analysis_id")))
            except (ValueError, TypeError, AttributeError):
                pass
    return {str(job.pk): deepcopy(job.result.get("valuation", {}))
            for job in AnalysisJob.objects.filter(pk__in=ids).order_by("created_at")}


def _valuation_identity_matches(data, valuation):
    identity = valuation.get("identity", {})
    # Insufficient identity is a valid result with a concrete missing-data note.
    if not isinstance(identity, dict) or not all(
        not identity.get(key) or _reference_text(data.get(key)) == _reference_text(identity[key])
        for key in ("brand", "model")):
        return False
    status = valuation.get("status")
    if status not in {"estimated", "conditional_reference"}:
        return True
    from .valuation import _market_hint
    if identity.get("market_hint") != _market_hint(data.get("location_country")):
        return False
    if any(_reference_text(data.get(key)) != _reference_text(value)
           for key, value in identity.get("compatibility", {}).items()):
        return False
    condition = {"Nueva": "new", "Usada": "used", "Reacondicionada": "refurbished",
                 "Para reparación": "for_repair"}.get(data.get("condition"))
    if data.get("operating_status") == "No funciona (declarado por el propietario)":
        condition = "for_repair"
    if condition is None and data.get("usage_condition") == "Usada":
        condition = "used"
    if identity.get("condition") and condition != identity["condition"]:
        return False
    if status == "conditional_reference" and condition is not None:
        reference_conditions = {item.get("condition") for item in valuation.get("comparables", [])
                                if isinstance(item, dict) and item.get("condition")}
        if reference_conditions and condition not in reference_conditions:
            return False
    return all(_reference_text(data.get(key)) == _reference_text(value)
               for key, value in identity.get("configurations", {}).items())


def public_valuation(snapshot):
    """Publish only signed, identity-compatible references, never raw AI output."""
    from .valuation import is_validated_estimate
    data, provenance = snapshot.get("data", {}), snapshot.get("provenance", {})
    manifests = snapshot.get("valuations", {})
    ids = {meta.get("analysis_id") for key, meta in provenance.items()
           if key in VALUATION_KEYS and data.get(key) not in (None, "")
           and isinstance(meta, dict) and meta.get("source") == "valuation"}
    serials = {_reference_text(data.get(key)) for key in ("serial", "vin")} - {""}
    for job_id, valuation in reversed(list(manifests.items())):
        if job_id not in ids or not is_validated_estimate(valuation) or not _valuation_identity_matches(data, valuation):
            continue
        safe = {key: deepcopy(valuation[key]) for key in ("status", "fields", "suggested_price", "label") if key in valuation}
        safe["fields"] = {key: data[key] for key in ESTIMATE_LABELS if data.get(key) not in (None, "")
                          and not any(serial in _reference_text(data[key]) for serial in serials)}
        # The suggested amount has its own editable field. The owner's asking
        # price and currency are independent and must never replace it.
        safe["suggested_price"] = data.get("estimate_suggested_price")
        safe["edited"] = any(_human_provenance_value(provenance.get(key)) for key in ESTIMATE_LABELS if data.get(key) not in (None, ""))
        safe["comparables"] = []
        for item in valuation.get("comparables", []):
            url = _public_reference_url(item.get("url"), serials)
            if not url:
                continue
            clean = {key: deepcopy(item[key]) for key in ("title", "price", "currency", "market", "price_type", "retrieved_at", "condition") if key in item}
            if any(serial in _reference_text(value) for serial in serials for value in clean.values()):
                continue
            safe["comparables"].append({**clean, "url": url})
        return safe
    return {}


def _human_provenance_value(meta):
    return isinstance(meta, dict) and (meta.get("source") == "user" or meta.get("review") == "confirmed")


def machine_valuation(machine):
    return public_valuation({"data": machine.data, "provenance": machine.provenance,
                             "valuations": valuations_for_provenance(machine.provenance)})


def _remove_incompatible_valuation(machine):
    from .valuation import is_validated_estimate
    manifests = valuations_for_provenance(machine.provenance)
    removed = []
    for key, meta in list(machine.provenance.items()):
        if key not in VALUATION_KEYS or not isinstance(meta, dict) or meta.get("source") != "valuation" or _human_provenance_value(meta):
            continue
        valuation = manifests.get(meta.get("analysis_id"), {})
        if is_validated_estimate(valuation) and not _valuation_identity_matches(machine.data, valuation):
            machine.data.pop(key, None)
            machine.provenance.pop(key, None)
            removed.append(key)
    return removed


def _family_identity_unchanged(machine, manifest):
    """A family proposal never becomes a model identifier or ignores an edit."""
    from .family_reference import family_identity_matches
    if not isinstance(manifest, dict) or not family_identity_matches(machine.data, manifest):
        return False
    if _human_provenance(machine, "model_family") and not machine.data.get("model_family"):
        return False
    category = manifest.get("identity", {}).get("category")
    return bool(machine.category_id and category and _reference_text(category) in {
        _reference_text(machine.category.name), _reference_text(machine.category.slug)})


def _family_market_matches_condition(data, manifest):
    """A used-equipment reference cannot price a declared repair-only machine."""
    condition = {"Nueva": "new", "Usada": "used", "Reacondicionada": "refurbished",
                 "Para reparación": "for_repair"}.get(data.get("condition"))
    if data.get("operating_status") == "No funciona (declarado por el propietario)":
        condition = "for_repair"
    if condition is None:
        condition = {"Usada": "used", "Aparentemente nueva": "new"}.get(data.get("usage_condition"))
    if condition is None:
        return True
    comparables = manifest.get("comparables", []) if isinstance(manifest, dict) else []
    conditions = {item.get("condition") for item in comparables if isinstance(item, dict)}
    return bool(comparables) and conditions == {condition}


def _remove_incompatible_family_values(machine):
    """Retire automatic family ranges after corrections; keep human declarations."""
    if not any(isinstance(meta, dict) and meta.get("source") == "family_reference"
               for meta in machine.provenance.values()):
        return []
    from .family_reference import is_validated_family_field
    ids = set()
    for meta in machine.provenance.values():
        if isinstance(meta, dict) and meta.get("source") == "family_reference" and meta.get("analysis_id"):
            try:
                ids.add(UUID(meta["analysis_id"]))
            except (ValueError, TypeError, AttributeError):
                pass
    jobs = {str(job.pk): job for job in AnalysisJob.objects.filter(pk__in=ids, machine=machine)}
    identity_valid = {key: _family_identity_unchanged(machine, job.result.get("family_reference", {}))
                      for key, job in jobs.items()}
    removed = []
    for key, meta in list(machine.provenance.items()):
        if not isinstance(meta, dict) or meta.get("source") != "family_reference" or _human_provenance(machine, key):
            continue
        job = jobs.get(meta.get("analysis_id"))
        valid = bool(job and identity_valid.get(str(job.pk))
                     and is_validated_family_field(job.result, key, machine.data.get(key), meta))
        if key in ESTIMATE_LABELS and job and not _family_market_matches_condition(
                machine.data, job.result.get("family_reference", {})):
            valid = False
        if key in AGE_LABELS and machine.data.get("year") not in (None, ""):
            valid = False
        if not valid:
            machine.data.pop(key, None)
            machine.provenance.pop(key, None)
            removed.append(key)
    return removed


def _remove_incompatible_age(machine):
    """Retire automatic age proposals when identity changes or an exact year arrives."""
    job_ids = set()
    for key in AGE_LABELS:
        meta = machine.provenance.get(key, {})
        if not _human_provenance_value(meta) and meta.get("analysis_id"):
            try:
                job_ids.add(UUID(meta["analysis_id"]))
            except (ValueError, TypeError):
                pass
    jobs = {str(job.pk): job for job in AnalysisJob.objects.filter(pk__in=job_ids, machine=machine)}
    removed = []
    for key in AGE_LABELS:
        meta = machine.provenance.get(key, {})
        if _human_provenance_value(meta) or meta.get("source") not in {"visual_proposal", "web"}:
            continue
        job = jobs.get(meta.get("analysis_id"))
        identity = job.result.get("data", {}) if job and isinstance(job.result, dict) else {}
        if meta.get("source") == "web" and job:
            identity = job.result.get("research", {}).get("identity", {})
        if machine.data.get("year") not in (None, "") or (job and not _reference_identity_matches(machine.data, machine.provenance, identity, "model")):
            machine.data.pop(key, None)
            machine.provenance.pop(key, None)
            removed.append(key)
    return removed


def detected_plate_asset_ids(machine):
    """Classify visible plate evidence without changing the uploaded originals.

    New per-image observations distinguish a plate close-up from a whole machine.
    Older results only identify the plate-bearing asset and remain private.
    """
    current = {str(pk) for pk in machine.assets.filter(kind="image").values_list("pk", flat=True)}
    seen, plates = set(), set()
    for job in machine.analysis_jobs.filter(status="completed").order_by("-created_at", "-pk").only("asset_ids", "result"):
        if not isinstance(job.result, dict) or not isinstance(job.asset_ids, list):
            continue
        allowed = current.intersection(job.asset_ids)
        observations = job.result.get("image_observations", [])
        if isinstance(observations, list):
            for item in observations:
                if not isinstance(item, dict) or item.get("kind") not in {"plate", "machine", "detail", "other"}:
                    continue
                identifier = item.get("asset_id")
                if identifier in allowed and identifier not in seen:
                    seen.add(identifier)
                    if item["kind"] == "plate":
                        plates.add(identifier)
        for item in job.result.get("plates", []):
            identifier = item.get("asset_id") if isinstance(item, dict) else None
            if identifier in allowed and identifier not in seen:
                seen.add(identifier)
                plates.add(identifier)
    return plates


def _web_identity_unchanged(machine, job, scope):
    identity = job.result.get("research", {}).get("identity", {})
    return _reference_identity_matches(machine.data, machine.provenance, identity, scope)


def _remove_incompatible_web_values(machine):
    """A corrected identity cannot retain unconfirmed specs of the old model.

    Verify the old signed result rather than trusting editable provenance alone.
    Historical jobs/versions and human confirmations remain untouched.
    """
    from .research import is_validated_web_field
    manifests = web_research_for_provenance(machine.provenance)
    removed = []
    for key, meta in list(machine.provenance.items()):
        if not isinstance(meta, dict) or meta.get("source") != "web" or _human_provenance(machine, key):
            continue
        manifest = manifests.get(meta.get("analysis_id"), {})
        if (not is_validated_web_field({"research": manifest}, key, machine.data.get(key), meta)
                or _reference_identity_matches(machine.data, machine.provenance, manifest.get("identity"), meta.get("scope"))):
            continue
        machine.data.pop(key, None)
        machine.provenance.pop(key, None)
        removed.append(key)
    return removed


def _web_value_keeps_serial_private(machine, job, value):
    identity = job.result.get("research", {}).get("identity", {})
    serials = {_reference_text(machine.data.get("serial")), _reference_text(machine.data.get("vin")),
               _reference_text(identity.get("serial") if isinstance(identity, dict) else None)} - {""}
    return not any(serial in _reference_text(value) for serial in serials)


class DraftRevisionConflict(ValidationError):
    """An optimistic concurrency conflict, distinct from invalid form values."""


def _empty_suggestion_target(machine, key):
    value = machine.title if key == "title" else machine.category_id if key == "category" else machine.data.get(key)
    return value is None or value == "" or (isinstance(value, str) and not value.strip()) or (key == "title" and value == "Mi maquinaria")


def _human_provenance(machine, key):
    meta = machine.provenance.get(key, {})
    return isinstance(meta, dict) and (meta.get("source") == "user" or meta.get("review") == "confirmed")


def _analysis_asset_state(machine):
    return [{"id": str(a.pk), "sha256": a.sha256, "purpose": a.purpose, "kind": a.kind,
             "status": a.processing_status} for a in machine.assets.exclude(purpose="document").order_by("id")]


def _analysis_snapshot_asset_state(assets):
    """Normalize pre-document-exclusion snapshots without weakening photo checks."""
    if not isinstance(assets, list):
        return None
    return [asset for asset in assets if not isinstance(asset, dict) or asset.get("purpose") != "document"]


def _automatic_description_record(machine):
    value = machine.data.get("description")
    meta = machine.provenance.get("description", {})
    if (not isinstance(value, str) or not value.strip() or not isinstance(meta, dict)
            or meta.get("source") not in {"system", "visual_proposal", "image"}
            or not isinstance(meta.get("analysis_id"), str) or not meta["analysis_id"]
            or _human_provenance(machine, "description")):
        return None
    return {"value": value, "provenance": deepcopy(meta)}


def _automatic_field_record(machine, key):
    """Only a still-unconfirmed AI value may be refreshed by a new analysis."""
    if key == "description":
        return _automatic_description_record(machine)
    value = machine.title if key == "title" else machine.category_id if key == "category" else machine.data.get(key)
    meta = machine.provenance.get(key, {})
    if (value in (None, "") or not isinstance(meta, dict) or _human_provenance(machine, key)
            or meta.get("source") not in {"system", "visual_proposal", "image", "plate", "web", "valuation", "family_reference"}
            or not isinstance(meta.get("analysis_id"), str) or not meta["analysis_id"]):
        return None
    return {"value": value, "provenance": deepcopy(meta)}


def automatic_application_snapshot(machine):
    """Private, durable pre-request state. This metadata is never sent to OpenAI."""
    eligible = {key for key in AUTOMATIC_DATA_FIELDS | {"title", "category"}
                if _empty_suggestion_target(machine, key) and not _human_provenance(machine, key)}
    snapshot = {"schema": 1, "owner_id": str(machine.owner_id), "revision": machine.revision,
                "assets": _analysis_asset_state(machine)}
    refresh = _automatic_description_record(machine)
    if refresh is not None:
        snapshot["refresh_description"] = refresh
        eligible.add("description")
    refresh_fields = {}
    for key in AUTOMATIC_DATA_FIELDS | {"title", "category"}:
        record = _automatic_field_record(machine, key)
        if record is not None:
            refresh_fields[key] = record
            eligible.add(key)
    snapshot["refresh_fields"] = refresh_fields
    snapshot["eligible_fields"] = sorted(eligible)
    return snapshot


def automatic_application_status(job):
    if job.application_result:
        return {**job.application_result, "requested": job.auto_apply}
    return {"requested": job.auto_apply, "status": "pending" if job.auto_apply and job.status in {"queued", "running"} else "skipped" if job.auto_apply else "disabled",
            "applied_fields": [], "skipped_fields": [], "field_reasons": {},
            "reason": "analysis_failed" if job.auto_apply and job.status == "failed" else "",
            "revision_before": None, "revision_after": None}


def _analysis_relevance_status(job):
    relevance = job.result.get("relevance")
    return relevance.get("status") if job.mode == "analysis" and isinstance(relevance, dict) else None


def _analysis_excludes_asset(job, meta):
    relevance = job.result.get("relevance")
    if job.mode != "analysis" or not isinstance(relevance, dict) or not isinstance(meta, dict):
        return False
    for key in ("excluded_asset_ids", "uncertain_asset_ids"):
        excluded = relevance.get(key)
        if isinstance(excluded, list) and meta.get("asset_id") and meta["asset_id"] in excluded:
            return True
    return False


def _clear_profile_visual_classification(machine, job, key, value, meta):
    """Admit only a saved visual proposal for a closed category classification."""
    if (not isinstance(meta, dict) or meta.get("source") != "visual_proposal"
            or meta.get("review") != "needs_review" or meta.get("component") != "machine"
            or not meta.get("asset_id") or str(meta["asset_id"]) not in job.asset_ids):
        return False
    from .category_profiles import profile_for_category
    choices = profile_for_category(machine.category).get("classification", {}).get(key, [])
    if value not in {item.get("value") for item in choices if isinstance(item, dict)}:
        return False
    return any(isinstance(item, dict) and item.get("key") == key and item.get("value") == value
               and item.get("source") == meta["source"] and item.get("review") == meta["review"]
               and item.get("component") == meta["component"] and item.get("asset_id") == meta["asset_id"]
               and item.get("evidence") == meta.get("evidence")
               for item in job.result.get("fields", []))


def _clear_automatic_field(machine, job, key, value, meta):
    if job.result.get("blocking_reason") in {"multiple_machines", "category_conflict"}:
        return False
    if _analysis_relevance_status(job) in {"unrelated", "uncertain"} or _analysis_excludes_asset(job, meta):
        return False
    if not isinstance(value, (str, int, float)) or isinstance(value, bool) or value is None or str(value).strip() == "":
        return False
    if meta.get("source") == "family_reference":
        from .family_reference import is_validated_family_field
        return (key in {"model_family", *AGE_LABELS, *ESTIMATE_LABELS}
                and key != "estimate_suggested_price"
                and _family_identity_unchanged(machine, job.result.get("family_reference", {}))
                and (key not in ESTIMATE_LABELS or _family_market_matches_condition(
                    machine.data, job.result.get("family_reference", {})))
                and _web_value_keeps_serial_private(machine, job, value)
                and is_validated_family_field(job.result, key, value, meta))
    if key == "model_family":
        # Neither a raw visual guess nor an exact-model reference can create it.
        return False
    if key in VALUATION_KEYS:
        from .valuation import is_validated_estimate
        valuation = job.result.get("valuation", {})
        values = valuation.get("fields", {})
        expected = valuation.get("suggested_price") if key in {"price", "estimate_suggested_price"} else values.get("estimate_currency") if key == "currency" else values.get(key)
        return (meta.get("source") == "valuation" and meta.get("review") == "needs_review"
                and is_validated_estimate(valuation) and str(value) == str(expected))
    if key in AGE_LABELS and meta.get("source") != "web":
        from .processing import age_estimate_fields
        field = age_estimate_fields(job.result).get(key, {})
        return (meta.get("source") == "visual_proposal" and field.get("value") == value and meta.get("review") == "needs_review"
                and meta.get("asset_id") in job.asset_ids and meta.get("asset_id") == field.get("asset_id")
                and meta.get("evidence") == field.get("evidence"))
    if key in VISUAL_LABELS:
        from .processing import visual_assessment_fields
        field = visual_assessment_fields(job.result).get(key, {})
        return (meta.get("source") == "visual_proposal" and field.get("value") == value and meta.get("review") == "needs_review"
                and meta.get("asset_id") in job.asset_ids and meta.get("asset_id") == field.get("asset_id")
                and meta.get("evidence") == field.get("evidence"))
    if _clear_profile_visual_classification(machine, job, key, value, meta):
        return True
    if meta.get("source") == "web":
        if key not in WEB_DATA_FIELDS | {"year"} or meta.get("review") != "needs_review" or meta.get("component") != "machine":
            return False
        if meta.get("scope") not in {"model", "exact_serial"} or (key == "year" and meta.get("scope") != "exact_serial"):
            return False
        from .research import is_validated_web_field
        return is_validated_web_field(job.result, key, value, meta)
    if key in {"title", "description"}:
        return isinstance(value, str) and meta.get("source") in {"visual_proposal", "image", "user", "system"} and meta.get("review") in {"needs_review", "clear"}
    if meta.get("component") != "machine" or meta.get("review") != "clear" or meta.get("source") not in {"plate", "image"}:
        return False
    if not meta.get("asset_id") or str(meta["asset_id"]) not in job.asset_ids:
        return False
    if key == "serial":
        if meta.get("source") != "plate" or re.search(r"[?\[\]*]|ilegible|unreadable", str(value), re.I):
            return False
        from .processing import plate_serial_is_clear
        return any(plate_serial_is_clear({"key": "serial", "value": value, **meta}, p)
                   for p in job.result.get("plates", []) if isinstance(p, dict))
    return True


def _visual_description_for_completion(machine, job):
    """Use only the separate visual narrative, never the precomposed web text.

    The processing boundary strips technical and private values. Recheck against
    the saved draft here because a human correction may have arrived meanwhile.
    """
    if _analysis_relevance_status(job) in {"unrelated", "uncertain"}:
        return ""
    text = job.result.get("visual_description")
    if job.mode != "analysis" or not isinstance(text, str) or not text.strip():
        return ""
    research = job.result.get("research", {})
    if isinstance(research, dict) and isinstance(research.get("identity"), dict):
        scope = "exact_serial" if research["identity"].get("serial") else "model"
        if not _web_identity_unchanged(machine, job, scope):
            return ""
    description_key = _reference_text(text)
    for key, value in job.result.get("data", {}).items():
        if key not in AUTOMATIC_DATA_FIELDS - {"description"} or value in (None, ""):
            continue
        if (_reference_text(value) in description_key
                and _reference_text(value) != _reference_text(machine.data.get(key))):
            # An uncertain/rejected value must not sneak back through prose.
            return ""
    category = job.result.get("category")
    if category and _human_provenance(machine, "category"):
        current = machine.category
        if not current or _reference_text(category) not in {_reference_text(current.name), _reference_text(current.slug)}:
            return ""
    return text.strip()


@transaction.atomic
def apply_analysis_automatically(machine, user, job, expected_revision=None, *, from_worker=False):
    """Fill gaps or refresh unchanged AI suggestions, once; never approve."""
    # Same lock order as save/submit and the worker completion path.
    machine = Machine.all_objects.select_for_update().get(pk=machine.pk)
    user = User.objects.get(pk=user.pk)
    if not from_worker:
        require_owner(machine, user)
        if machine.owner_id != user.pk:
            raise PermissionDenied("El propietario debe autorizar el completado de su borrador.")
    job_id = job.pk if isinstance(job, AnalysisJob) else job
    try:
        job = AnalysisJob.objects.select_for_update().get(pk=job_id, machine=machine, status="completed")
    except (AnalysisJob.DoesNotExist, ValueError, ValidationError):
        raise ValidationError("El análisis no está disponible para esta maquinaria.")
    # A retry after a lost response must not reinsert a value the user later cleared.
    retry_failed_application = not from_worker and job.application_result.get("reason") == "application_failed"
    if job.application_result and not retry_failed_application:
        return machine, automatic_application_status(job)
    if not from_worker and (type(expected_revision) is not int or expected_revision != machine.revision):
        raise DraftRevisionConflict("El borrador cambió. Actualiza la página antes de completar los huecos.")
    if from_worker and not job.auto_apply:
        return machine, automatic_application_status(job)
    job.auto_apply = True
    result = {"requested": True, "status": "skipped", "applied_fields": [], "skipped_fields": [],
              "field_reasons": {}, "reason": "", "revision_before": machine.revision, "revision_after": machine.revision}

    def finish(reason=""):
        result["reason"] = reason
        job.application_result = result
        job.save(update_fields=["auto_apply", "application_result"])
        return machine, result

    if machine.deleted_at is not None or job.result.get("draft_deleted"):
        return finish("draft_deleted")
    if job.result.get("blocking_reason") in {"multiple_machines", "category_conflict"}:
        return finish(job.result["blocking_reason"])
    if machine.owner_id != job.requested_by_id or user.pk != job.requested_by_id or not user.is_active:
        return finish("owner_changed")
    if not machine.editable:
        return finish("not_editable")
    consent = Consent.objects.filter(user=user, machine=machine, kind="ai").order_by("-created_at", "-pk").first()
    if not consent or not consent.granted:
        return finish("consent_revoked")
    relevance = _analysis_relevance_status(job)
    if relevance in {"unrelated", "uncertain"}:
        # A successful image check can find no machinery. Preserve the draft
        # exactly instead of applying fallback titles or recomposing old facts.
        return finish("images_" + relevance)
    base = job.application_snapshot
    legacy = not base
    if legacy:
        # Older completed jobs have no durable input snapshot. Exact revision is
        # required; subsequent human corrections or media changes invalidate reuse.
        if machine.revision != job.revision:
            return finish("draft_changed")
        eligible = AUTOMATIC_DATA_FIELDS | {"title", "category"}
    else:
        if base.get("schema") != 1 or base.get("owner_id") != str(machine.owner_id) or base.get("revision") != job.revision or machine.revision < job.revision:
            return finish("draft_changed")
        if _analysis_snapshot_asset_state(base.get("assets")) != _analysis_asset_state(machine):
            return finish("assets_changed")
        eligible = set(base.get("eligible_fields", []))
    current_assets = {str(a.pk) for a in machine.assets.filter(kind="image", processing_status="ready").exclude(purpose="document")}
    if not isinstance(job.asset_ids, list) or not set(job.asset_ids).issubset(current_assets) or (job.mode == "analysis" and not job.asset_ids):
        return finish("assets_changed")
    candidates = job.result.get("data", {})
    provenance = job.result.get("provenance", {})
    if not isinstance(candidates, dict) or not isinstance(provenance, dict):
        return finish("invalid_result")

    def skip(key, reason):
        result["skipped_fields"].append(key)
        result["field_reasons"][key] = reason

    def can_fill(key):
        refresh_fields = base.get("refresh_fields", {}) if not legacy else {}
        refresh_field = refresh_fields.get(key) if isinstance(refresh_fields, dict) else None
        if (key in eligible and isinstance(refresh_field, dict)
                and refresh_field == _automatic_field_record(machine, key)):
            return True
        refresh = base.get("refresh_description") if not legacy else None
        if (key == "description" and key in eligible and isinstance(refresh, dict)
                and refresh == _automatic_description_record(machine)):
            return True
        if not _empty_suggestion_target(machine, key):
            skip(key, "existing_value")
            return False
        meta = machine.provenance.get(key, {})
        # The old form marked untouched blanks as user-confirmed. At the exact
        # legacy revision, allow those empty placeholders once, but never an
        # accepted AI field or any correction made after that analysis.
        legacy_blank = (legacy and key != "serial" and isinstance(meta, dict)
                        and meta.get("source") == "user" and not meta.get("analysis_id"))
        if _human_provenance(machine, key) and not legacy_blank:
            skip(key, "human_correction")
            return False
        if key not in eligible:
            skip(key, "not_empty_at_request")
            return False
        return True

    def add_validated(key, value, meta):
        candidate = deepcopy(machine)
        payload = {"provenance": {key: {**meta, "analysis_id": str(job.pk)}}}
        if key in {"title", "category"}:
            payload[key] = value
        else:
            payload["data"] = {key: value}
        try:
            _validate_payload(candidate, payload, trusted_provenance=True)
        except ValidationError:
            skip(key, "invalid_value")
            return
        machine.title, machine.category_id = candidate.title, candidate.category_id
        machine.data, machine.provenance = candidate.data, candidate.provenance
        if key == "hours" and meta.get("source") in {"image", "plate"}:
            related_values = {"hours_basis": "hourmeter" if meta.get("source") == "image" else "documented",
                              "hours_recorded_at": timezone.localdate().isoformat()}
            for related, related_value in related_values.items():
                if not _human_provenance(machine, related):
                    machine.data[related] = related_value
                    machine.provenance[related] = {**meta, "analysis_id": str(job.pk)}
        result["applied_fields"].append(key)

    research = job.result.get("research")
    compose_after_research = any(key in candidates for key in AGE_LABELS) or (isinstance(research, dict) and research.get("status") != "disabled") or any(
        key in WEB_DATA_FIELDS | {"year"} and machine.data.get(key) not in (None, "")
        and isinstance(meta, dict) and meta.get("source") == "web"
        for key, meta in machine.provenance.items())
    conflicting_fields = []
    estimate_protected = any(_human_provenance(machine, key) for key in ESTIMATE_LABELS)
    cleared_valuation = []
    valuation = job.result.get("valuation", {})
    if valuation.get("status") in {"insufficient", "not_run"} and not estimate_protected:
        from .valuation import is_validated_estimate
        if is_validated_estimate(valuation) and _valuation_identity_matches(machine.data, valuation):
            # Do not pair an old automatic range with a new message saying that
            # no estimate was possible. Remove only unchanged AI suggestions
            # captured at admission; a human price or explicit blank survives.
            for key in VALUATION_KEYS:
                record = base.get("refresh_fields", {}).get(key)
                if (isinstance(record, dict) and record.get("provenance", {}).get("source") == "valuation"
                        and record == _automatic_field_record(machine, key)):
                    machine.data.pop(key, None)
                    machine.provenance.pop(key, None)
                    cleared_valuation.append(key)
    # Apply clear readings before model references so a corrected AI identity
    # can receive its own research, while human identity changes still reject it.
    candidate_items = sorted(candidates.items(), key=lambda item: (item[0] == "description",
                             (2 if isinstance(provenance.get(item[0]), dict) and provenance[item[0]].get("source") == "valuation" else
                              1 if isinstance(provenance.get(item[0]), dict) and provenance[item[0]].get("source") in {"web", "family_reference"} else 0)))
    for key, value in candidate_items:
        if key not in AUTOMATIC_DATA_FIELDS | {"title"}:
            continue
        if key in AGE_LABELS:
            # A range and its basis are one proposal, applied atomically below.
            continue
        if key in ESTIMATE_LABELS and estimate_protected:
            skip(key, "human_correction")
            continue
        if key in {"price", "currency", "estimate_min", "estimate_max", "estimate_currency"}:
            # Apply this pair together below; never attach a foreign price to a
            # currency the owner selected while the analysis was running.
            continue
        if key == "description" and (compose_after_research or conflicting_fields):
            # Compose from the final accepted fields below, never from a web
            # candidate discarded because of uncertainty or a human correction.
            continue
        meta = provenance.get(key, {})
        if not isinstance(meta, dict) or not _clear_automatic_field(machine, job, key, value, meta):
            skip(key, "not_identifiable" if value is None or value == "" else "uncertain")
            continue
        if meta.get("source") == "valuation" and not _valuation_identity_matches(machine.data, job.result.get("valuation", {})):
            skip(key, "identity_changed")
            continue
        if meta.get("source") == "web" and not _web_identity_unchanged(machine, job, meta.get("scope")):
            skip(key, "identity_changed")
            continue
        if meta.get("source") == "web" and not _web_value_keeps_serial_private(machine, job, value):
            skip(key, "private_identifier")
            continue
        existing_meta = machine.provenance.get(key, {})
        if (meta.get("source") == "web" and isinstance(existing_meta, dict)
                and existing_meta.get("source") in {"plate", "image"}
                and (existing_meta.get("review") in {"clear", "confirmed"}
                     or existing_meta.get("review_reason") == "conflicting_reading")
                and not _empty_suggestion_target(machine, key)):
            # A catalog reference cannot replace a reading of this unit merely
            # because both were generated automatically at different times.
            skip(key, "existing_unit_reading")
            continue
        if can_fill(key):
            if _same_image_numeric_conflict(machine, key, value, meta):
                machine.provenance[key] = {**existing_meta, "review": "needs_review", "review_reason": "conflicting_reading"}
                conflicting_fields.append(key)
                skip(key, "conflicting_reading")
                continue
            add_validated(key, value, meta)
    age_protected = any(_human_provenance(machine, key) for key in AGE_LABELS)
    age_keys = list(AGE_LABELS)
    if any(key in candidates for key in age_keys):
        if age_protected or machine.data.get("year") not in (None, ""):
            for key in age_keys:
                if key in candidates:
                    skip(key, "human_correction" if age_protected else "known_year")
        elif all(key in candidates and _clear_automatic_field(machine, job, key, candidates[key], provenance.get(key, {})) for key in age_keys):
            same_source = len({provenance[key].get("source") for key in age_keys}) == 1
            identity_ok = all(provenance[key].get("source") != "web" or (
                _web_identity_unchanged(machine, job, provenance[key].get("scope"))
                and _web_value_keeps_serial_private(machine, job, candidates[key])) for key in age_keys)
            if same_source and identity_ok and all(can_fill(key) for key in age_keys):
                candidate = deepcopy(machine)
                try:
                    _validate_payload(candidate, {"data": {key: candidates[key] for key in age_keys},
                        "provenance": {key: {**provenance[key], "analysis_id": str(job.pk)} for key in age_keys}}, trusted_provenance=True)
                    machine.data, machine.provenance = candidate.data, candidate.provenance
                    result["applied_fields"].extend(age_keys)
                except ValidationError:
                    for key in age_keys:
                        skip(key, "invalid_value")
            else:
                for key in age_keys:
                    skip(key, "identity_changed" if not identity_ok else "incomplete_range")
        else:
            for key in age_keys:
                if key in candidates:
                    skip(key, "incomplete_range")
    valuation = job.result.get("valuation", {})
    range_keys = [key for key in ("estimate_min", "estimate_max", "estimate_currency") if not estimate_protected and key in candidates
                  and _clear_automatic_field(machine, job, key, candidates[key], provenance.get(key, {}))
                  and (provenance.get(key, {}).get("source") == "family_reference"
                       or _valuation_identity_matches(machine.data, valuation)) and can_fill(key)]
    if len(range_keys) == 3 and len({provenance[key].get("source") for key in range_keys}) == 1:
        candidate = deepcopy(machine)
        try:
            _validate_payload(candidate, {"data": {key: candidates[key] for key in range_keys},
                "provenance": {key: {**provenance[key], "analysis_id": str(job.pk)} for key in range_keys}}, trusted_provenance=True)
            machine.data, machine.provenance = candidate.data, candidate.provenance
            result["applied_fields"].extend(range_keys)
        except ValidationError:
            for key in range_keys:
                skip(key, "invalid_value")
    # Even historical jobs must not silently turn an estimate into an asking price.
    for key in ("price", "currency"):
        if key in candidates and provenance.get(key, {}).get("source") == "valuation":
            skip(key, "owner_price_required")
    category = job.result.get("category")
    if isinstance(category, str) and category.strip() and can_fill("category"):
        def normalized(text):
            return " ".join("".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).casefold().split())
        wanted = normalized(category)
        matches = [item for item in Category.objects.filter(active=True) if wanted in {normalized(item.name), normalized(item.slug)}]
        if len(matches) == 1:
            add_validated("category", matches[0].pk, {"source": "visual_proposal", "review": "needs_review"})
        else:
            skip("category", "no_exact_category")
    invalidated = cleared_valuation + _remove_incompatible_web_values(machine) + _remove_incompatible_valuation(machine) + _remove_incompatible_age(machine) + _remove_incompatible_family_values(machine)
    if invalidated:
        result["invalidated_fields"] = invalidated
    if conflicting_fields:
        result["conflicting_fields"] = conflicting_fields
    if (compose_after_research or invalidated or conflicting_fields) and can_fill("description"):
        from .research import compose_description
        private_identifiers = [machine.data.get("serial"), candidates.get("serial"),
                               (research or {}).get("identity", {}).get("serial")]
        private_identifiers.extend(field.get("value") for field in job.result.get("fields", [])
                                   if isinstance(field, dict) and field.get("key") == "serial")
        description = compose_description(machine.data, machine.provenance,
                                          machine.category.name if machine.category_id else None,
                                          visual_description=_visual_description_for_completion(machine, job),
                                          private_identifiers=private_identifiers)
        if description:
            add_validated("description", description, {"source": "system", "review": "needs_review"})
    if result["applied_fields"] or invalidated or conflicting_fields:
        machine.revision += 1
        if machine.status in {"approved", "rejected", "cancelled"}:
            machine.status = "draft"
        machine.save(update_fields=["title", "category", "data", "provenance", "revision", "status", "updated_at"])
        result["status"] = "applied"
        result["revision_after"] = machine.revision
        audit(user, "analysis.automatically_applied", machine, {"job_id": str(job.pk), "fields": result["applied_fields"],
              "invalidated_fields": invalidated, "conflicting_fields": conflicting_fields, "revision": machine.revision})
    else:
        result["status"] = "no_changes"
    return finish()


def audit(actor, action, obj, metadata=None):
    return AuditEvent.objects.create(actor=actor if actor and actor.is_authenticated else None,
                                     action=action, object_type=obj._meta.label_lower,
                                     object_id=str(obj.pk), metadata=metadata or {})


def require_operator(actor, permission):
    if not actor or not actor.is_active or not actor.is_staff or not actor.has_perm(permission):
        raise PermissionDenied("No tienes permiso para realizar esta operación.")


def require_owner(machine, user):
    if not user or not user.is_active:
        raise PermissionDenied("Debes iniciar sesión.")
    if machine.owner_id != user.pk:
        require_operator(user, "portal.change_machine")


def _notify(user, machine, kind, subject, body, template_key=None, context=None):
    if user.is_guest:
        return
    template=NotificationTemplate.objects.filter(key=template_key or kind,active=True).first()
    if template:
        values={"folio":machine.folio if machine else "", "status":machine.get_status_display() if machine else "", "reason":body,
                "title":machine.title if machine else "", "name":user.get_full_name() or user.email, "portal_url":getattr(settings,"PUBLIC_URL","")+"/panel/"}
        values.update(context or {})
        try:
            template.full_clean()
            subject=Template(template.subject).substitute(values)[:180].replace("\r","").replace("\n"," ")
            body=Template(template.body).substitute(values)
        except (ValidationError,ValueError,KeyError):
            # Invalid out-of-band configuration cannot lose an important workflow notification.
            audit(None,"notification.template_invalid",template)
    Notification.objects.create(user=user, machine=machine, kind=kind, subject=subject, body=body,
                                channel="in_app", status="sent", sent_at=timezone.now())
    Notification.objects.create(user=user, machine=machine, kind=kind, subject=subject, body=body, channel="email")


def _validate_payload(machine, payload, trusted_provenance=False):
    previous_data = deepcopy(machine.data)
    previous_provenance = deepcopy(machine.provenance)
    previous_title = machine.title
    previous_category = machine.category_id
    if not isinstance(payload, dict) or set(payload) - {"title", "category", "data", "provenance"}:
        raise ValidationError("La actualización contiene campos no permitidos.")
    if "title" in payload:
        title = payload["title"]
        if not isinstance(title, str) or not title.strip() or len(title) > 180:
            raise ValidationError({"title": "Escribe un título de hasta 180 caracteres."})
        machine.title = title.strip()
    if "category" in payload:
        category = payload["category"]
        if category in (None, ""):
            machine.category = None
        else:
            try:
                machine.category = Category.objects.get(pk=category, active=True)
            except (Category.DoesNotExist, ValueError, TypeError):
                raise ValidationError({"category": "Selecciona una categoría disponible."})
    allowed = DATA_FIELDS.copy()
    if machine.category_id:
        for field in machine.category.fields:
            if isinstance(field, str):
                allowed.add(field)
            elif isinstance(field, dict) and isinstance(field.get("key"), str):
                allowed.add(field["key"])
    if "data" in payload:
        data = payload["data"]
        if not isinstance(data, dict) or set(data) - allowed:
            raise ValidationError({"data": "Los datos contienen campos no admitidos para esta categoría."})
        clean = {}
        if "model_family" in data and data["model_family"] not in (None, "") and (
                not isinstance(data["model_family"], str) or len(data["model_family"].strip()) > 100):
            raise ValidationError({"model_family": "Escribe una familia de modelo de hasta 100 caracteres."})
        for key, value in data.items():
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValidationError({"data": f"El campo {key} debe contener texto o un número."})
            if isinstance(value, str):
                value = value.strip()
                if len(value) > (12000 if key in {"description", "notes", "plate_transcription"} else 2000 if key in VISUAL_LABELS or key in ESTIMATE_LABELS or key == "estimated_year_basis" else 1000):
                    raise ValidationError({"data": f"El campo {key} es demasiado largo."})
            clean[key] = value
        from .structured_data import parse_decimal, validate_manual_data
        numeric_fields = {"year", "hours", "kilometers", "price", "estimated_year_from", "estimated_year_to",
                          "estimate_min", "estimate_max", "estimate_suggested_price"}
        for key in numeric_fields & clean.keys():
            value = clean[key]
            if value is None or isinstance(value, str) and value.casefold() in {"", "n/a", "por definir", "desconocido", "consultar", "consultar precio"}:
                clean[key] = None
                continue
            number = parse_decimal(value)
            if number is None or not number.is_finite():
                raise ValidationError({key: "Escribe un número sin separadores de miles; usa punto o coma decimal."})
            clean[key] = int(number) if number == number.to_integral_value() else float(number)
        validate_manual_data({**machine.data, **clean}, machine.category)
        if clean.get("estimate_date"):
            from datetime import date
            try:
                estimate_date = date.fromisoformat(clean["estimate_date"])
                if estimate_date > timezone.localdate():
                    raise ValueError
            except (TypeError, ValueError):
                raise ValidationError({"estimate_date": "Usa una fecha válida AAAA-MM-DD que no esté en el futuro."})
        if clean.get("price") not in (None, "", "consultar", "Consultar precio"):
            try:
                price = Decimal(str(clean["price"]))
                if not price.is_finite() or price < 0 or price > Decimal("999999999999"):
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                raise ValidationError({"price": "Escribe un precio válido o déjalo vacío para consultar."})
        for key in ("currency", "estimate_currency"):
            if clean.get(key) and clean[key] not in {"MXN", "USD", "EUR"}:
                raise ValidationError({key: "Selecciona MXN, USD o EUR."})
        for key in ("estimate_min", "estimate_max", "estimate_suggested_price"):
            if clean.get(key) not in (None, ""):
                try:
                    number = Decimal(str(clean[key]))
                    if not number.is_finite() or number < 0 or number > Decimal("999999999999"):
                        raise InvalidOperation
                except (InvalidOperation, ValueError):
                    raise ValidationError({key: "Escribe un valor orientativo válido o déjalo vacío."})
        merged = {**machine.data, **clean}
        if all(merged.get(key) not in (None, "") for key in ("estimate_min", "estimate_max")):
            try:
                if Decimal(str(merged["estimate_min"])) > Decimal(str(merged["estimate_max"])):
                    raise ValidationError({"estimate_min": "El mínimo no puede superar al máximo."})
            except InvalidOperation:
                raise ValidationError({"estimate_min": "El rango de valor debe contener números válidos."})
        for key, choices in VISUAL_CHOICES.items():
            if clean.get(key) not in (None, "") and clean[key] not in choices:
                raise ValidationError({key: "Selecciona una de las opciones disponibles."})
        for key in ("year", "hours", "kilometers", "estimated_year_from", "estimated_year_to"):
            if clean.get(key) not in (None, ""):
                try:
                    number = Decimal(str(clean[key]))
                    if not number.is_finite() or number < 0:
                        raise InvalidOperation
                    if key == "year" and (number < 1900 or number > timezone.now().year + 1 or number != int(number)):
                        raise InvalidOperation
                    if key in {"estimated_year_from", "estimated_year_to"} and (number < 1900 or number > timezone.now().year or number != int(number)):
                        raise InvalidOperation
                except (InvalidOperation, ValueError):
                    raise ValidationError({key: "Escribe un valor válido o déjalo sin completar."})
        if all(merged.get(key) not in (None, "") for key in ("estimated_year_from", "estimated_year_to")):
            try:
                if Decimal(str(merged["estimated_year_from"])) > Decimal(str(merged["estimated_year_to"])):
                    raise ValidationError({"estimated_year_from": "El inicio del rango no puede superar al final."})
            except InvalidOperation:
                raise ValidationError({"estimated_year_from": "Escribe años válidos para el rango aproximado."})
        machine.data = {**machine.data, **clean}
    if "provenance" in payload:
        provenance = deepcopy(payload["provenance"])
        if not isinstance(provenance, dict) or set(provenance) - (allowed | {"title","category"}):
            raise ValidationError({"provenance": "La procedencia contiene campos no admitidos."})
        valid_assets = {str(pk) for pk in machine.assets.values_list("id", flat=True)}
        for key, value in provenance.items():
            meta_keys = {"source", "review", "review_reason", "asset_id", "source_url", "source_title", "source_date", "scope", "basis", "match", "matched_serial", "label", "component", "transcription", "evidence", "analysis_id", "confidence", "identity_scope"}
            if trusted_provenance and key in AGE_LABELS:
                meta_keys |= {"period_origin", "period_records"}
            if not isinstance(value, dict) or set(value) - meta_keys:
                raise ValidationError({"provenance": "La procedencia debe indicar origen y revisión."})
            if any(item is not None and (not isinstance(item, str) or len(item) > 12000)
                   for name, item in value.items() if name != "period_records"):
                raise ValidationError({"provenance": "Formato de procedencia inválido."})
            if {"period_origin", "period_records"} & value.keys():
                records = value.get("period_records")
                if (value.get("source") != "web" or value.get("period_origin") != "lectura_catalogue_metadata_v1"
                        or not isinstance(records, list) or not 1 <= len(records) <= 4
                        or any(not isinstance(record, dict)
                               or set(record) != {"source_url", "source_title", "start_year", "end_year"}
                               or any(not isinstance(item, str) or len(item) > 2000 for item in record.values())
                               for record in records)):
                    raise ValidationError({"provenance": "Los periodos deben proceder de una referencia validada."})
            if value.get("asset_id") and value["asset_id"] not in valid_assets:
                raise ValidationError({"provenance": "El archivo de procedencia no pertenece a esta maquinaria."})
            unchanged=(previous_title==machine.title if key=="title" else previous_category==machine.category_id if key=="category" else previous_data.get(key)==machine.data.get(key))
            if not trusted_provenance and value.get("source")=="user":
                original=previous_provenance.get(key,{})
                provenance[key]={**original,"review":"confirmed"} if unchanged and original else {"source":"user","review":"confirmed"}
                continue
            if not trusted_provenance and unchanged:
                original = previous_provenance.get(key, {})
                for field, item in value.items():
                    if field != "review" and item != original.get(field) and not (field == "source" and not original and item == "user"):
                        raise ValidationError({"provenance": "La fuente sólo puede proceder de un análisis guardado; puedes confirmar o corregir el dato."})
        machine.provenance = {**machine.provenance, **deepcopy(provenance)}
    # Browsers cannot forge AI/image/external provenance. Explicit correction stays a user declaration.
    if not trusted_provenance:
        for key in payload.get("data", {}):
            if previous_data.get(key) != machine.data.get(key) or key not in previous_provenance:
                machine.provenance[key] = {"source": "user", "review": "confirmed", "source_date": timezone.now().isoformat(), "confidence": "owner_declared"}
        if "hours" in payload.get("data", {}) and previous_data.get("hours") != machine.data.get("hours"):
            present = machine.data.get("hours") is not None
            machine.data["hours_basis"] = payload["data"].get("hours_basis") or ("owner_declared" if present else None)
            machine.data["hours_recorded_at"] = payload["data"].get("hours_recorded_at") or (timezone.localdate().isoformat() if present else None)
            for key in ("hours_basis", "hours_recorded_at"):
                machine.provenance[key] = {"source": "user", "review": "confirmed", "source_date": timezone.now().isoformat()}
        if "title" in payload and previous_title != machine.title:
            machine.provenance["title"] = {"source": "user", "review": "confirmed"}
        if "category" in payload and previous_category != machine.category_id:
            machine.provenance["category"] = {"source": "user", "review": "confirmed"}


@transaction.atomic
def save_draft(machine, user, payload, expected_revision):
    machine = Machine.objects.select_for_update(of=("self",)).select_related("category").get(pk=machine.pk)
    require_owner(machine, user)
    if not machine.editable:
        raise ValidationError("La solicitud está en revisión. Espera una respuesta antes de editarla.")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision != machine.revision:
        raise DraftRevisionConflict("El borrador cambió en otra ventana. Actualiza la página para recuperar la versión actual.")
    _validate_payload(machine, payload)
    invalidated_web = _remove_incompatible_web_values(machine)
    _remove_incompatible_valuation(machine)
    invalidated_age = _remove_incompatible_age(machine)
    invalidated_family = _remove_incompatible_family_values(machine)
    if (invalidated_web or invalidated_age or invalidated_family or AGE_LABELS.keys() & payload.get("data", {}).keys()) and _automatic_description_record(machine):
        from .research import compose_description
        machine.data["description"] = compose_description(machine.data, machine.provenance,
            machine.category.name if machine.category_id else None, private_identifiers=[machine.data.get("serial")])
    machine.revision += 1
    if machine.status in {WorkflowStatus.APPROVED, WorkflowStatus.REJECTED, WorkflowStatus.CANCELLED}:
        machine.status = WorkflowStatus.DRAFT
    machine.save()
    audit(user, "machine.draft_saved", machine, {"revision": machine.revision, "fields": sorted(payload.keys())})
    return machine


@transaction.atomic
def apply_analysis_suggestions(machine, user, job, fields, expected_revision):
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    require_owner(machine, user)
    if not machine.editable:
        raise ValidationError("La maquinaria está en revisión y no se puede modificar.")
    if machine.revision != expected_revision or not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise ValidationError("El borrador cambió. Actualiza la página antes de aplicar sugerencias.")
    job_id = job.pk if isinstance(job, AnalysisJob) else job
    try:
        job = AnalysisJob.objects.get(pk=job_id, machine=machine, status="completed")
    except (AnalysisJob.DoesNotExist, ValueError, ValidationError):
        raise ValidationError("El análisis no está disponible para esta maquinaria.")
    after_automatic = job.application_result.get("revision_after") if job.application_result.get("status") in {"applied", "no_changes"} else None
    if job.revision != machine.revision and after_automatic != machine.revision:
        raise ValidationError("El borrador cambió después del análisis. Solicita un nuevo análisis para conservar tus correcciones.")
    if job.result.get("blocking_reason") in {"multiple_machines", "category_conflict"}:
        raise ValidationError("Revisa el tipo de maquinaria y separa las fotos de equipos diferentes antes de aplicar datos.")
    if _analysis_relevance_status(job) in {"unrelated", "uncertain"}:
        raise ValidationError("Estas fotos no permiten identificar maquinaria. Agrega una foto del equipo o de su placa y vuelve a preparar la ficha.")
    if not isinstance(fields, list) or not fields or any(not isinstance(field, str) for field in fields):
        raise ValidationError("Selecciona los datos que deseas aplicar.")
    result_data = job.result.get("data", {})
    result_provenance = job.result.get("provenance", {})
    if set(fields) - set(result_data) or set(fields) - (DATA_FIELDS | {"title"}):
        raise ValidationError("Las sugerencias seleccionadas no pertenecen al análisis.")
    if set(fields) & AGE_LABELS.keys() and not AGE_LABELS.keys() <= set(fields):
        raise ValidationError("Aplica el rango de año aproximado junto con su explicación.")
    for amount_keys, currency_key in (({"price"}, "currency"), ({"estimate_min", "estimate_max"}, "estimate_currency")):
        if (set(fields) & amount_keys and any(result_provenance.get(key, {}).get("source") in {"valuation", "family_reference"} for key in set(fields) & amount_keys)
                and currency_key not in fields and machine.data.get(currency_key) != result_data.get(currency_key)):
            raise ValidationError("Aplica el importe junto con su moneda de referencia.")
    payload = {"data": {}, "provenance": {}}
    for key in set(fields):
        value = result_data[key]
        if value in (None, ""):
            continue
        if _analysis_excludes_asset(job, result_provenance.get(key, {})):
            raise ValidationError("Ese dato procede de una foto que no permite identificar maquinaria. Usa una foto del equipo o de su placa.")
        if key in VISUAL_LABELS.keys() | AGE_LABELS.keys() and not _clear_automatic_field(machine, job, key, value, result_provenance.get(key, {})):
            raise ValidationError("La observación visual no está validada para esta fotografía.")
        if result_provenance.get(key, {}).get("source") == "family_reference" and not _clear_automatic_field(
                machine, job, key, value, result_provenance[key]):
            raise ValidationError("La referencia de familia no está validada para estos datos y esta maquinaria.")
        if result_provenance.get(key, {}).get("source") == "valuation" and (
                not _clear_automatic_field(machine, job, key, value, result_provenance[key])
                or not _valuation_identity_matches(machine.data, job.result.get("valuation", {}))):
            raise ValidationError("La estimación no está validada para esta maquinaria.")
        if result_provenance.get(key, {}).get("source") == "web" and (
                not _clear_automatic_field(machine, job, key, value, result_provenance[key])
                or not _web_identity_unchanged(machine, job, result_provenance[key].get("scope"))
                or not _web_value_keeps_serial_private(machine, job, value)):
            raise ValidationError("La referencia web no está validada para este dato y esta maquinaria.")
        if key == "title":
            payload["title"] = value
        else:
            payload["data"][key] = value
        provenance = deepcopy(result_provenance.get(key, {"source": "visual_proposal"}))
        provenance["review"] = "confirmed"
        provenance["analysis_id"] = str(job.pk)
        payload["provenance"][key] = provenance
    _validate_payload(machine, payload, trusted_provenance=True)
    invalidated = _remove_incompatible_web_values(machine) + _remove_incompatible_valuation(machine) + _remove_incompatible_age(machine) + _remove_incompatible_family_values(machine)
    if invalidated and _automatic_description_record(machine):
        from .research import compose_description
        machine.data["description"] = compose_description(machine.data, machine.provenance,
            machine.category.name if machine.category_id else None)
    machine.revision += 1
    if machine.status in {"approved", "rejected", "cancelled"}:
        machine.status = "draft"
    machine.save()
    audit(user, "analysis.suggestions_applied", machine, {"job_id": str(job.pk), "fields": sorted(fields), "revision": machine.revision})
    return machine


@transaction.atomic
def snapshot(machine, user):
    machine = Machine.objects.select_for_update(of=("self",)).select_related("category").get(pk=machine.pk)
    require_owner(machine, user)
    assets = list(machine.assets.filter(processing_status="ready"))
    plate_ids = detected_plate_asset_ids(machine)
    number = (machine.versions.aggregate(value=Max("number"))["value"] or 0) + 1
    contact = machine.consents.filter(kind="contact",user_id=machine.owner_id).order_by("-created_at", "-pk").first()
    public_contact = {}
    if contact and contact.granted and machine.data.get("contact_public"):
        if isinstance(machine.data["contact_public"], str):
            public_contact = {"text": machine.data["contact_public"]}
        else:
            owner = machine.owner
            public_contact = {"name": owner.get_full_name(), "email": owner.email, "phone": owner.phone, "company": owner.company}
    from .structured_data import structured_snapshot, version_search_fields
    search = version_search_fields(machine.data, machine.category, machine.provenance)
    return MachineVersion.objects.create(machine=machine, number=number, created_by=user, **search, data={
        "title": machine.title, "category": machine.category_id,
        "category_name": machine.category.name if machine.category_id else "",
        "data": deepcopy(machine.data), "provenance": deepcopy(machine.provenance),
        "structured": structured_snapshot(machine.data, machine.category),
        "web_research": web_research_for_provenance(machine.provenance),
        "valuations": valuations_for_provenance(machine.provenance),
        "asset_ids": [str(asset.pk) for asset in assets],
        "private_plate_asset_ids": sorted(plate_ids),
        "public_asset_ids": [str(asset.pk) for asset in assets if asset.public_authorized and asset.purpose not in {"plate", "document"} and str(asset.pk) not in plate_ids],
        "contact_authorized": bool(contact and contact.granted), "public_contact": public_contact, "revision": machine.revision,
    })


@transaction.atomic
def submit_machine(machine, user, advertise_consent, contact_consent=False):
    machine = Machine.objects.select_for_update().select_related("owner").get(pk=machine.pk)
    require_owner(machine, user)
    if machine.owner_id!=user.pk:
        raise PermissionDenied("El anunciante debe autorizar y enviar personalmente su solicitud.")
    if not machine.editable:
        raise ValidationError("Esta maquinaria ya tiene una solicitud en revisión.")
    if machine.owner.advertiser_status in {"suspended", "rejected"}:
        raise ValidationError("Tu permiso de anunciante necesita revisión de IMC antes de enviar otra solicitud.")
    if advertise_consent is not True:
        raise ValidationError("Autoriza el envío de la ficha para revisión y difusión.")
    from .intake import require_consistent_photos
    require_consistent_photos(machine)
    if not machine.assets.filter(kind="image", processing_status="ready", purpose__in=["general", "detail"]).exists():
        from .intake import require_prepared_serial
        require_prepared_serial(machine)
    # A failed or unavailable analysis must not turn unknown specifications into
    # mandatory manual work. These neutral labels make no claim about the machine.
    fallback_fields = []
    if _empty_suggestion_target(machine, "title") and not _human_provenance(machine, "title"):
        machine.title = "Maquinaria para revisión"
        machine.provenance["title"] = {"source": "system", "review": "needs_review"}
        fallback_fields.append("title")
    if _empty_suggestion_target(machine, "description") and not _human_provenance(machine, "description"):
        machine.data["description"] = "Maquinaria presentada para revisión con fotografías adjuntas. Las características, la condición y la disponibilidad están pendientes de confirmar con el anunciante."
        machine.provenance["description"] = {"source": "system", "review": "needs_review"}
        fallback_fields.append("description")
    if fallback_fields:
        machine.revision += 1
        machine.save(update_fields=["title", "data", "provenance", "revision", "updated_at"])
        audit(user, "machine.submission_labels_prepared", machine, {"fields": fallback_fields, "revision": machine.revision})
    Consent.objects.create(user=user, machine=machine, kind="advertise", granted=True)
    Consent.objects.create(user=user, machine=machine, kind="contact", granted=contact_consent is True)
    version = snapshot(machine, user)
    submission = Submission.objects.create(machine=machine, version=version)
    machine.status = WorkflowStatus.SUBMITTED
    machine.save(update_fields=["status", "updated_at"])
    audit(user, "submission.created", submission, {"version": version.number})
    _notify(machine.owner, machine, "submission", f"{machine.folio}: solicitud recibida", "Tu maquinaria fue enviada a revisión de IMC México. Enviar una solicitud no equivale a estar publicado.")
    return submission


LOCAL_DUPLICATE_REVIEW_RESULTS = {"no_match", "match", "update", "legitimate", "inconclusive"}


def _local_duplicate_review_event(machine, submission):
    """Return the human decision recorded for this exact submitted snapshot."""
    events = AuditEvent.objects.filter(
        action="machine.local_duplicate_reviewed", object_type=Machine._meta.label_lower,
        object_id=str(machine.pk), created_at__gte=submission.created_at,
    ).select_related("actor").order_by("-created_at")
    for event in events:
        metadata = event.metadata if isinstance(event.metadata, dict) else {}
        if metadata.get("submission_id") == submission.pk and metadata.get("version_id") == submission.version_id:
            return event
    return None


@transaction.atomic
def record_local_duplicate_review(machine, submission, actor, result, evidence, limitations=""):
    """Record a staff decision without merging or rejecting any machine automatically."""
    require_operator(actor, "portal.review_submission")
    if result not in LOCAL_DUPLICATE_REVIEW_RESULTS:
        raise ValidationError("Selecciona el resultado de la revisión local de duplicados.")
    evidence, limitations = str(evidence or "").strip(), str(limitations or "").strip()
    if not 12 <= len(evidence) <= 4000 or len(limitations) > 4000:
        raise ValidationError("Describe qué se comprobó; los límites de la revisión son opcionales.")
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    submission = Submission.objects.select_for_update().select_related("version").get(pk=submission.pk)
    if submission.machine_id != machine.pk or submission.status not in {"submitted", "in_review"}:
        raise ValidationError("La revisión local debe corresponder a una solicitud pendiente de esta maquinaria.")
    candidates = []
    if actor.has_perm("portal.view_machine"):
        candidates = [str(item.pk) for item in find_possible_duplicates(machine, actor)]
    return audit(actor, "machine.local_duplicate_reviewed", machine, {
        "submission_id": submission.pk, "version_id": submission.version_id, "result": result,
        "evidence": evidence, "limitations": limitations, "candidate_machine_ids": candidates,
    })


@transaction.atomic
def review_submission(submission, actor, decision, reason=""):
    require_operator(actor, "portal.review_submission")
    # Consistent lock order: machine before submission, matching submit/edit.
    machine = Machine.objects.select_for_update().select_related("owner").get(pk=submission.machine_id)
    submission = Submission.objects.select_for_update().select_related("version").get(pk=submission.pk)
    if decision not in {"in_review", "changes_requested", "approved", "rejected", "cancelled"}:
        raise ValidationError("Decisión de revisión no válida.")
    if submission.status not in {"submitted", "in_review"}:
        raise ValidationError("Esta solicitud ya fue resuelta. Revisa la solicitud más reciente.")
    if machine.submissions.order_by("-created_at", "-pk").first().pk != submission.pk:
        raise ValidationError("Sólo puede resolverse la solicitud más reciente.")
    reason = str(reason or "").strip()
    if decision in {"changes_requested", "rejected", "cancelled"} and not reason:
        raise ValidationError("Indica el motivo y, cuando corresponda, qué debe corregirse.")
    if decision == "approved" and machine.owner.advertiser_status != "approved":
        raise ValidationError("Aprueba primero el permiso de anunciante del propietario.")
    if decision == "approved" and not _local_duplicate_review_event(machine, submission):
        raise ValidationError("Registra primero una revisión local de posibles duplicados para esta solicitud y versión.")
    if submission.version.machine_id != machine.pk:
        raise ValidationError("La versión no corresponde a la maquinaria.")
    original_version = submission.version
    approved_version = None
    if decision == "approved":
        approved_data = deepcopy(original_version.data)
        allowed_assets = approved_data.get("asset_ids", [])
        # A running reading can identify a plate after the advertiser submitted
        # the snapshot. Preserve that restriction before any public approval.
        approved_data["private_plate_asset_ids"] = sorted(
            set(approved_data.get("private_plate_asset_ids", []))
            | (detected_plate_asset_ids(machine) & set(allowed_assets)))
        approved_data["public_asset_ids"] = [str(pk) for pk in machine.assets.filter(
            pk__in=allowed_assets, processing_status="ready", public_authorized=True,
            purpose__in=["general", "detail"]).exclude(pk__in=approved_data.get("private_plate_asset_ids", [])).values_list("pk", flat=True)]
        approved_version = MachineVersion.objects.create(machine=machine,
            number=(machine.versions.aggregate(value=Max("number"))["value"] or 0) + 1,
            data=approved_data, created_by=actor)
    submission.status = decision
    submission.message = reason
    submission.decided_by = actor
    submission.decided_at = timezone.now()
    submission.save(update_fields=["status", "message", "decided_by", "decided_at"])
    machine.status = decision
    if decision == "approved":
        machine.approved_version = approved_version
        # Approval never auto-publishes, and a new approved version requires a new explicit publication.
        for publication in machine.publications.select_for_update():
            publication.enabled = False
            publication.status = "disabled"
            publication.save(update_fields=["enabled", "status", "updated_at"])
    machine.save(update_fields=["status", "approved_version", "updated_at"])
    if reason:
        Message.objects.create(machine=machine, sender=actor, body=reason)
    audit(actor, f"submission.{decision}", submission, {"reason": reason, "version": original_version.number, "approved_version": approved_version.number if approved_version else None})
    _notify(machine.owner, machine, "review", f"{machine.folio}: {submission.get_status_display()}", reason or "Consulta el estado actualizado de tu solicitud en el panel. La publicación requiere autorización independiente.",template_key="review_"+decision)
    return submission


def _locked_owner_draft(machine, user, expected_revision):
    machine = Machine.all_objects.select_for_update().get(pk=machine.pk)
    if not user.is_authenticated or not user.is_active or machine.owner_id != user.pk or not User.objects.filter(pk=user.pk, is_active=True).exists():
        raise PermissionDenied("Sólo el propietario puede gestionar su papelera.")
    if type(expected_revision) is not int or expected_revision != machine.revision:
        raise DraftRevisionConflict("El borrador cambió. Actualiza la página antes de continuar.")
    if machine.status != WorkflowStatus.DRAFT or machine.approved_version_id is not None:
        raise ValidationError("Sólo puedes eliminar o restaurar borradores sin una versión aprobada.")
    if machine.publications.filter(Q(enabled=True) | Q(status="published")).exists():
        raise ValidationError("La maquinaria tiene una publicación activa y no puede ir a la papelera.")
    return machine


@transaction.atomic
def delete_draft(machine, user, expected_revision):
    """Retain all files and history; only the owner can trash an unpublished draft."""
    machine = _locked_owner_draft(machine, user, expected_revision)
    if machine.deleted_at is not None:
        raise ValidationError("El borrador ya está en la papelera.")
    machine.deleted_at = timezone.now()
    machine.revision += 1
    machine.save(update_fields=["deleted_at", "revision", "updated_at"])
    from .processing import cancel_deleted_draft_jobs
    cancel_deleted_draft_jobs(machine)
    audit(user, "machine.draft_deleted", machine, {"revision": machine.revision, "deleted_at": machine.deleted_at.isoformat()})
    return machine


@transaction.atomic
def restore_draft(machine, user, expected_revision):
    machine = _locked_owner_draft(machine, user, expected_revision)
    if machine.deleted_at is None:
        raise ValidationError("El borrador no está en la papelera.")
    previous_deleted_at = machine.deleted_at
    machine.deleted_at = None
    machine.revision += 1
    machine.save(update_fields=["deleted_at", "revision", "updated_at"])
    audit(user, "machine.draft_restored", machine, {"revision": machine.revision, "deleted_at": previous_deleted_at.isoformat()})
    return machine


@transaction.atomic
def set_availability(machine, user, value):
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    require_owner(machine, user)
    if value not in Machine.Availability.values:
        raise ValidationError("Disponibilidad no válida.")
    previous = machine.availability
    machine.availability = value
    machine.save(update_fields=["availability", "updated_at"])
    if value == "withdrawn":
        machine.publications.update(enabled=False, status="disabled")
        PreparedShare.objects.filter(machine=machine).update(enabled=False)
    audit(user, "machine.availability", machine, {"from": previous, "to": value})
    return machine


@transaction.atomic
def duplicate_machine(machine, user):
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    require_owner(machine, user)
    duplicate = Machine.objects.create(owner=user, title=f"Copia de {machine.title}"[:180], category=machine.category,
                                       data=deepcopy(machine.data), provenance={})
    duplicate.data.pop("contact_public", None)
    asset_mapping = {}
    written_files = []
    try:
        for source in machine.assets.filter(processing_status="ready"):
            new = Asset(machine=duplicate, revision=1, kind=source.kind, purpose=source.purpose,
                        mime_type=source.mime_type, size=source.size, sha256=source.sha256,
                        position=source.position, is_cover=source.is_cover, public_authorized=False,
                        processing_status=source.processing_status)
            for name in ("original", "preview"):
                original = getattr(source, name)
                if original:
                    with original.open("rb") as handle:
                        getattr(new, name).save(original.name.rsplit("/", 1)[-1], ContentFile(handle.read()), save=False)
                    written_files.append((getattr(new, name).storage, getattr(new, name).name))
            new.save()
            asset_mapping[str(source.pk)] = str(new.pk)
        duplicate.provenance = deepcopy(machine.provenance)
        for provenance in duplicate.provenance.values():
            if isinstance(provenance, dict) and provenance.get("asset_id"):
                provenance["asset_id"] = asset_mapping.get(provenance["asset_id"])
        duplicate.save(update_fields=["data", "provenance"])
        audit(user, "machine.duplicated", duplicate, {"source": str(machine.pk)})
    except Exception:
        for storage, name in written_files:
            storage.delete(name)
        raise
    return duplicate


@transaction.atomic
def set_advertiser_status(user, actor, status, reason=""):
    require_operator(actor, "portal.manage_advertisers")
    if user.pk == actor.pk:
        raise PermissionDenied("Otro administrador debe modificar tu permiso de anunciante.")
    if status not in User.AdvertiserStatus.values:
        raise ValidationError("Estado de anunciante no válido.")
    if not str(reason or "").strip():
        raise ValidationError("Registra el motivo de la decisión sobre el anunciante.")
    user = User.objects.select_for_update().get(pk=user.pk)
    previous = user.advertiser_status
    user.advertiser_status = status
    user.save(update_fields=["advertiser_status"])
    if status != "approved":
        Publication.objects.filter(machine__owner=user).update(enabled=False, status="disabled")
    if status in {"rejected", "suspended"}:
        PreparedShare.objects.filter(machine__owner=user).update(enabled=False)
    audit(actor, "advertiser.status_changed", user, {"from": previous, "to": status, "reason": reason})
    _notify(user, None, "advertiser", "Actualización de tu permiso de anunciante", reason)
    return user


@transaction.atomic
def set_publication(machine, actor, enabled, destination="share"):
    require_operator(actor, "portal.publish_machine")
    machine = Machine.objects.select_for_update(of=("self",)).select_related("owner", "approved_version").get(pk=machine.pk)
    if destination not in {"share", "main"}:
        raise ValidationError("Destino no válido.")
    if enabled and (not machine.approved_version_id or machine.owner.advertiser_status != "approved"):
        raise ValidationError("Se requiere una versión y un anunciante aprobados.")
    if enabled and machine.availability == "withdrawn":
        raise ValidationError("La maquinaria está retirada.")
    if enabled and not machine.approved_version.data.get("public_asset_ids"):
        raise ValidationError("La versión aprobada no tiene fotografías autorizadas para difusión.")
    publication, _ = Publication.objects.get_or_create(machine=machine, destination=destination)
    publication.version = machine.approved_version
    publication.enabled = bool(enabled) and destination == "share"
    publication.status = ("published" if destination == "share" else "approved") if enabled else "disabled"
    publication.full_clean()
    publication.save()
    audit(actor, "publication.enabled" if enabled else "publication.disabled", publication, {"destination": destination})
    return publication


@transaction.atomic
def reassign_machine(machine, actor, new_owner, reason):
    """Exceptional transfer: invalidate publication and require fresh owner consent/review."""
    require_operator(actor,"portal.reassign_machine")
    if not str(reason or "").strip():
        raise ValidationError("Registra la justificación de la reasignación excepcional.")
    machine=Machine.objects.select_for_update().get(pk=machine.pk)
    new_owner=User.objects.get(pk=new_owner.pk)
    if not new_owner.is_active or new_owner.advertiser_status in {"suspended","rejected"}:
        raise ValidationError("La cuenta de destino debe estar activa y habilitada para preparar anuncios.")
    if machine.owner_id==new_owner.pk:
        raise ValidationError("La maquinaria ya pertenece a esta cuenta.")
    previous_owner=machine.owner
    machine.publications.update(enabled=False,status="disabled")
    PreparedShare.objects.filter(machine=machine).update(enabled=False)
    for submission in machine.submissions.filter(status__in=["submitted","in_review"]):
        submission.status="cancelled"
        submission.message="Solicitud cancelada por reasignación administrativa: "+str(reason).strip()
        submission.decided_by=actor
        submission.decided_at=timezone.now()
        submission.save(update_fields=["status","message","decided_by","decided_at"])
    machine.owner=new_owner
    machine.status="draft"
    machine.approved_version=None
    machine.revision+=1
    machine.data={**machine.data,"contact_public":""}
    machine.assets.update(public_authorized=False)
    machine.save()
    audit(actor,"machine.owner_reassigned",machine,{"previous_owner":previous_owner.pk,"new_owner":new_owner.pk,"reason":str(reason).strip()})
    _notify(previous_owner,machine,"reassignment","Reasignación administrativa de maquinaria",f"{machine.folio}: {reason}")
    _notify(new_owner,machine,"reassignment","Maquinaria asignada a tu cuenta",f"{machine.folio}: revisa los datos y envía una nueva solicitud con tus autorizaciones.")
    return machine


def find_possible_duplicates(machine,actor):
    """Return suggestions only. Similar identifiers are not proof of duplicate ownership."""
    require_operator(actor,"portal.view_machine")
    criteria=Q(pk__in=[])
    serial=str(machine.data.get("serial") or "").strip()
    brand=str(machine.data.get("brand") or "").strip()
    model=str(machine.data.get("model") or "").strip()
    if len(serial)>=4:
        criteria|=Q(data__serial__iexact=serial)
    if brand and model:
        criteria|=Q(data__brand__iexact=brand,data__model__iexact=model)
    hashes=list(machine.assets.exclude(sha256="").values_list("sha256",flat=True)[:100])
    if hashes:
        criteria|=Q(assets__sha256__in=hashes)
    return Machine.objects.filter(criteria).exclude(pk=machine.pk).select_related("owner").distinct().order_by("-updated_at")[:10]


@transaction.atomic
def send_machine_reminder(machine,actor,reason):
    require_operator(actor,"portal.change_machine")
    if not str(reason or "").strip():
        raise ValidationError("Escribe el recordatorio concreto para el anunciante.")
    machine=Machine.objects.select_for_update().select_related("owner").get(pk=machine.pk)
    if not machine.owner.is_active:
        raise ValidationError("La cuenta del anunciante está inactiva.")
    _notify(machine.owner,machine,"reminder",f"{machine.folio}: recordatorio de IMC México",str(reason).strip())
    audit(actor,"machine.reminder_queued",machine,{"reason":str(reason).strip()})
