"""Transactional business boundary. Views and admin must use these operations."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import (AnalysisJob, Asset, AuditEvent, Category, Consent, Machine, MachineVersion,
                     Message, Notification, Publication, Submission, User, WorkflowStatus)


DATA_FIELDS = {"brand", "model", "year", "serial", "hours", "description", "location", "price", "currency", "condition", "notes", "contact_public", "plate_transcription", "plate_type", "plate_kind", "no_plate", "kilometers", "power", "capacity", "weight", "dimensions", "fuel", "attachments", "engine", "transmission"}


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


def _notify(user, machine, kind, subject, body):
    Notification.objects.create(user=user, machine=machine, kind=kind, subject=subject, body=body,
                                channel="in_app", status="sent", sent_at=timezone.now())
    Notification.objects.create(user=user, machine=machine, kind=kind, subject=subject, body=body, channel="email")


def _validate_payload(machine, payload, trusted_provenance=False):
    previous_data = deepcopy(machine.data)
    previous_provenance = deepcopy(machine.provenance)
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
        provenance = payload["provenance"]
        if not isinstance(provenance, dict) or set(provenance) - (allowed | {"title"}):
            raise ValidationError({"provenance": "La procedencia contiene campos no admitidos."})
        valid_assets = {str(pk) for pk in machine.assets.values_list("id", flat=True)}
        for key, value in provenance.items():
            if not isinstance(value, dict) or set(value) - {"source", "review", "asset_id", "source_url", "source_date", "label", "component", "transcription", "evidence", "analysis_id"}:
                raise ValidationError({"provenance": "La procedencia debe indicar origen y revisión."})
            if any(item is not None and (not isinstance(item, str) or len(item) > 12000) for item in value.values()):
                raise ValidationError({"provenance": "Formato de procedencia inválido."})
            if value.get("asset_id") and value["asset_id"] not in valid_assets:
                raise ValidationError({"provenance": "El archivo de procedencia no pertenece a esta maquinaria."})
            if not trusted_provenance and previous_data.get(key) == machine.data.get(key):
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


@transaction.atomic
def save_draft(machine, user, payload, expected_revision):
    machine = Machine.objects.select_for_update().select_related("category").get(pk=machine.pk)
    require_owner(machine, user)
    if not machine.editable:
        raise ValidationError("La solicitud está en revisión. Espera una respuesta antes de editarla.")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision != machine.revision:
        raise ValidationError("El borrador cambió en otra ventana. Actualiza la página para recuperar la versión actual.")
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
    machine = Machine.objects.select_for_update().select_related("category").get(pk=machine.pk)
    require_owner(machine, user)
    assets = list(machine.assets.filter(processing_status="ready"))
    number = (machine.versions.aggregate(value=Max("number"))["value"] or 0) + 1
    contact = machine.consents.filter(kind="contact").order_by("-created_at", "-pk").first()
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
        "asset_ids": [str(asset.pk) for asset in assets],
        "public_asset_ids": [str(asset.pk) for asset in assets if asset.public_authorized and asset.purpose not in {"plate", "document"}],
        "contact_authorized": bool(contact and contact.granted), "public_contact": public_contact, "revision": machine.revision,
    })


@transaction.atomic
def submit_machine(machine, user, advertise_consent, contact_consent=False):
    machine = Machine.objects.select_for_update().select_related("owner").get(pk=machine.pk)
    require_owner(machine, user)
    if not machine.editable:
        raise ValidationError("Esta maquinaria ya tiene una solicitud en revisión.")
    if machine.owner.advertiser_status in {"suspended", "rejected"}:
        raise ValidationError("Tu permiso de anunciante necesita revisión de IMC antes de enviar otra solicitud.")
    if advertise_consent is not True:
        raise ValidationError("Autoriza el envío de la ficha para revisión y difusión.")
    if not machine.title.strip() or machine.title == "Mi maquinaria":
        raise ValidationError({"title": "Indica un título que identifique el equipo."})
    if not str(machine.data.get("location") or "").strip():
        raise ValidationError({"location": "Indica la ubicación general del equipo."})
    if not machine.assets.filter(kind="image", processing_status="ready", purpose__in=["general", "detail"]).exists():
        raise ValidationError("Agrega al menos una fotografía general o de detalle del equipo.")
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
    _notify(machine.owner, machine, "review", f"{machine.folio}: {submission.get_status_display()}", reason or "Consulta el estado actualizado de tu solicitud en el panel. La publicación requiere autorización independiente.")
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
    machine = Machine.objects.select_for_update().select_related("owner", "approved_version").get(pk=machine.pk)
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
