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
                     Message, Notification, NotificationTemplate, Publication, Submission, User, WorkflowStatus)


DATA_FIELDS = {"brand", "model", "year", "serial", "hours", "description", "location", "price", "currency", "condition", "notes", "contact_public", "plate_transcription", "plate_type", "plate_kind", "no_plate", "kilometers", "power", "capacity", "weight", "dimensions", "fuel", "attachments", "engine", "transmission"}
AUTOMATIC_DATA_FIELDS = {"brand", "model", "year", "serial", "hours", "power", "weight", "capacity",
                         "dimensions", "fuel", "kilometers", "engine", "transmission", "description"}
WEB_DATA_FIELDS = {"brand", "model", "power", "weight", "capacity", "dimensions", "fuel", "engine", "transmission"}
WEB_FIELD_LABELS = {"brand": "Marca", "model": "Modelo", "power": "Potencia", "weight": "Peso",
                    "capacity": "Capacidad", "dimensions": "Dimensiones", "fuel": "Combustible",
                    "engine": "Motor", "transmission": "Transmisión", "year": "Año"}


def _reference_text(value):
    value = str(value or "")
    for _ in range(3):
        value = unquote(value)
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def _public_reference_url(url, serials):
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
        if any(_reference_text(key) in {"serial", "serialnumber", "serie", "numerodeserie", "vin", "pin", "sn"}
               for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            return ""
        if any(serial in _reference_text(url) for serial in serials):
            return ""
    except (ValueError, UnicodeError):
        return ""
    return url


def public_web_references(snapshot):
    """Public citation allowlist derived only from the displayed immutable data.

    Evidence, job IDs, plate IDs and serial identifiers never leave this helper.
    Unit-specific links and titles containing a private serial remain private.
    """
    data = snapshot.get("data", {})
    provenance = snapshot.get("provenance", {})
    if not isinstance(data, dict) or not isinstance(provenance, dict):
        return []
    serials = {_reference_text(data.get(key)) for key in ("serial", "vin") if data.get(key)} - {""}
    references = []
    for key, label in WEB_FIELD_LABELS.items():
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
        private_serials = serials | {_reference_text(identity.get("serial")), _reference_text(meta.get("matched_serial"))} - {""}
        title = re.sub(r"[\x00-\x1f\x7f]", " ", str(meta.get("source_title") or "Fuente de referencia"))[:500]
        url = _public_reference_url(meta.get("source_url"), private_serials)
        private_source = not url or any(serial in _reference_text(title) for serial in private_serials) or (meta["scope"] == "exact_serial" and not private_serials)
        references.append({"field": key, "label": label, "value": value, "scope": meta["scope"],
            "scope_label": "Referencia del modelo; confirmar en este equipo" if meta["scope"] == "model" else "Referencia de la unidad; sujeta a revisión",
            "source_url": "" if private_source else url,
            "source_title": "Fuente privada" if private_source else title,
            "private_source": private_source,
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


def _web_identity_unchanged(machine, job, scope):
    identity = job.result.get("research", {}).get("identity", {})
    if not isinstance(identity, dict):
        return False
    for key in ("brand", "model", "serial") if scope == "exact_serial" else ("brand", "model"):
        researched = identity.get(key)
        if not researched:
            continue
        current = machine.data.get(key)
        if current not in (None, "") and _reference_text(current) != _reference_text(researched):
            return False
        if _empty_suggestion_target(machine, key) and _human_provenance(machine, key):
            return False
    return True


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
             "status": a.processing_status} for a in machine.assets.order_by("id")]


def _automatic_description_record(machine):
    value = machine.data.get("description")
    meta = machine.provenance.get("description", {})
    if (not isinstance(value, str) or not value.strip() or not isinstance(meta, dict)
            or meta.get("source") not in {"system", "visual_proposal", "image"}
            or not isinstance(meta.get("analysis_id"), str) or not meta["analysis_id"]
            or _human_provenance(machine, "description")):
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
    snapshot["eligible_fields"] = sorted(eligible)
    return snapshot


def automatic_application_status(job):
    if job.application_result:
        return {**job.application_result, "requested": job.auto_apply}
    return {"requested": job.auto_apply, "status": "pending" if job.auto_apply and job.status in {"queued", "running"} else "skipped" if job.auto_apply else "disabled",
            "applied_fields": [], "skipped_fields": [], "field_reasons": {},
            "reason": "analysis_failed" if job.auto_apply and job.status == "failed" else "",
            "revision_before": None, "revision_after": None}


def _clear_automatic_field(job, key, value, meta):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool) or value is None or str(value).strip() == "":
        return False
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
        return any(p.get("asset_id") == meta["asset_id"] and p.get("component") == "machine" and p.get("readability") == "clear"
                   for p in job.result.get("plates", []) if isinstance(p, dict))
    return True


def _visual_description_for_completion(machine, job):
    """Use only the separate visual narrative, never the precomposed web text.

    The processing boundary strips technical and private values. Recheck against
    the saved draft here because a human correction may have arrived meanwhile.
    """
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
    """Fill gaps or refresh an unchanged AI description, once; never approve."""
    # Same lock order as save/submit and the worker completion path.
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
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

    if machine.owner_id != job.requested_by_id or user.pk != job.requested_by_id or not user.is_active:
        return finish("owner_changed")
    if not machine.editable:
        return finish("not_editable")
    consent = Consent.objects.filter(user=user, machine=machine, kind="ai").order_by("-created_at", "-pk").first()
    if not consent or not consent.granted:
        return finish("consent_revoked")
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
        if base.get("assets") != _analysis_asset_state(machine):
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
        result["applied_fields"].append(key)

    identity_at_completion = deepcopy(machine)
    research = job.result.get("research")
    compose_after_research = isinstance(research, dict) and research.get("status") != "disabled"
    for key, value in candidates.items():
        if key not in AUTOMATIC_DATA_FIELDS | {"title"}:
            continue
        if key == "description" and compose_after_research:
            # Compose from the final accepted fields below, never from a web
            # candidate discarded because of uncertainty or a human correction.
            continue
        meta = provenance.get(key, {})
        if not isinstance(meta, dict) or not _clear_automatic_field(job, key, value, meta):
            skip(key, "not_identifiable" if value is None or value == "" else "uncertain")
            continue
        if meta.get("source") == "web" and not _web_identity_unchanged(identity_at_completion, job, meta.get("scope")):
            skip(key, "identity_changed")
            continue
        if meta.get("source") == "web" and not _web_value_keeps_serial_private(identity_at_completion, job, value):
            skip(key, "private_identifier")
            continue
        if can_fill(key):
            add_validated(key, value, meta)
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
    if compose_after_research and can_fill("description"):
        from .research import compose_description
        private_identifiers = [machine.data.get("serial"), candidates.get("serial"),
                               research.get("identity", {}).get("serial")]
        private_identifiers.extend(field.get("value") for field in job.result.get("fields", [])
                                   if isinstance(field, dict) and field.get("key") == "serial")
        description = compose_description(machine.data, machine.provenance,
                                          machine.category.name if machine.category_id else None,
                                          visual_description=_visual_description_for_completion(machine, job),
                                          private_identifiers=private_identifiers)
        if description:
            add_validated("description", description, {"source": "system", "review": "needs_review"})
    if result["applied_fields"]:
        machine.revision += 1
        if machine.status in {"approved", "rejected", "cancelled"}:
            machine.status = "draft"
        machine.save(update_fields=["title", "category", "data", "provenance", "revision", "status", "updated_at"])
        result["status"] = "applied"
        result["revision_after"] = machine.revision
        audit(user, "analysis.automatically_applied", machine, {"job_id": str(job.pk), "fields": result["applied_fields"], "revision": machine.revision})
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
        for key, value in data.items():
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValidationError({"data": f"El campo {key} debe contener texto o un número."})
            if isinstance(value, str):
                value = value.strip()
                if len(value) > (12000 if key in {"description", "notes", "plate_transcription"} else 1000):
                    raise ValidationError({"data": f"El campo {key} es demasiado largo."})
            clean[key] = value
        if clean.get("price") not in (None, "", "consultar", "Consultar precio"):
            try:
                price = Decimal(str(clean["price"]))
                if not price.is_finite() or price < 0 or price > Decimal("999999999999"):
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                raise ValidationError({"price": "Escribe un precio válido o déjalo vacío para consultar."})
        if clean.get("currency") and clean["currency"] not in {"MXN", "USD", "EUR"}:
            raise ValidationError({"currency": "Selecciona MXN, USD o EUR."})
        for key in ("year", "hours", "kilometers"):
            if clean.get(key) not in (None, ""):
                try:
                    number = Decimal(str(clean[key]))
                    if not number.is_finite() or number < 0:
                        raise InvalidOperation
                    if key == "year" and (number < 1900 or number > timezone.now().year + 1 or number != int(number)):
                        raise InvalidOperation
                except (InvalidOperation, ValueError):
                    raise ValidationError({key: "Escribe un valor válido o déjalo sin completar."})
        machine.data = {**machine.data, **clean}
    if "provenance" in payload:
        provenance = deepcopy(payload["provenance"])
        if not isinstance(provenance, dict) or set(provenance) - (allowed | {"title","category"}):
            raise ValidationError({"provenance": "La procedencia contiene campos no admitidos."})
        valid_assets = {str(pk) for pk in machine.assets.values_list("id", flat=True)}
        for key, value in provenance.items():
            if not isinstance(value, dict) or set(value) - {"source", "review", "asset_id", "source_url", "source_title", "source_date", "scope", "basis", "match", "matched_serial", "label", "component", "transcription", "evidence", "analysis_id"}:
                raise ValidationError({"provenance": "La procedencia debe indicar origen y revisión."})
            if any(item is not None and (not isinstance(item, str) or len(item) > 12000) for item in value.values()):
                raise ValidationError({"provenance": "Formato de procedencia inválido."})
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
                machine.provenance[key] = {"source": "user", "review": "confirmed"}
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
    if job.revision != machine.revision:
        raise ValidationError("El borrador cambió después del análisis. Solicita un nuevo análisis para conservar tus correcciones.")
    if not isinstance(fields, list) or not fields or any(not isinstance(field, str) for field in fields):
        raise ValidationError("Selecciona los datos que deseas aplicar.")
    result_data = job.result.get("data", {})
    result_provenance = job.result.get("provenance", {})
    if set(fields) - set(result_data) or set(fields) - (DATA_FIELDS | {"title"}):
        raise ValidationError("Las sugerencias seleccionadas no pertenecen al análisis.")
    payload = {"data": {}, "provenance": {}}
    for key in set(fields):
        value = result_data[key]
        if value in (None, ""):
            continue
        if result_provenance.get(key, {}).get("source") == "web" and (
                not _clear_automatic_field(job, key, value, result_provenance[key])
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
    number = (machine.versions.aggregate(value=Max("number"))["value"] or 0) + 1
    contact = machine.consents.filter(kind="contact",user_id=machine.owner_id).order_by("-created_at", "-pk").first()
    public_contact = {}
    if contact and contact.granted and machine.data.get("contact_public"):
        if isinstance(machine.data["contact_public"], str):
            public_contact = {"text": machine.data["contact_public"]}
        else:
            owner = machine.owner
            public_contact = {"name": owner.get_full_name(), "email": owner.email, "phone": owner.phone, "company": owner.company}
    return MachineVersion.objects.create(machine=machine, number=number, created_by=user, data={
        "title": machine.title, "category": machine.category_id,
        "category_name": machine.category.name if machine.category_id else "",
        "data": deepcopy(machine.data), "provenance": deepcopy(machine.provenance),
        "web_research": web_research_for_provenance(machine.provenance),
        "asset_ids": [str(asset.pk) for asset in assets],
        "public_asset_ids": [str(asset.pk) for asset in assets if asset.public_authorized and asset.purpose not in {"plate", "document"}],
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
    if not machine.assets.filter(kind="image", processing_status="ready", purpose__in=["general", "detail"]).exists():
        raise ValidationError("Agrega al menos una fotografía general o de detalle del equipo.")
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
    if submission.version.machine_id != machine.pk:
        raise ValidationError("La versión no corresponde a la maquinaria.")
    original_version = submission.version
    approved_version = None
    if decision == "approved":
        approved_data = deepcopy(original_version.data)
        allowed_assets = approved_data.get("asset_ids", [])
        approved_data["public_asset_ids"] = [str(pk) for pk in machine.assets.filter(
            pk__in=allowed_assets, processing_status="ready", public_authorized=True,
            purpose__in=["general", "detail"]).values_list("pk", flat=True)]
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
