"""Short-lived visitor draft capability.

Visitors never authenticate as the technical owner.  The browser receives an
opaque session capability, while the normal Machine/Asset/AnalysisJob models
continue to own all saved work.  A successful account login atomically changes
the machine owner to the real account.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import AnalysisJob, Asset, Brand, Category, EquipmentModel, GuestDraft, Machine, PlatformSettings, User
from .security import throttle

SESSION_KEY = "guest_draft_capability"
MAX_GUEST_IMAGES = 3
MAX_GUEST_JOBS = 1
logger = logging.getLogger(__name__)


class GuestExpired(ValidationError):
    pass


def purge_expired_guest_drafts(*, limit=100):
    """Remove expired, unclaimed visitor work without racing an active worker.

    The first pass marks the normal Machine as deleted and cancels queued work.
    A running provider request is never removed below its worker: it retains a
    durable ``draft_deleted`` marker and is purged only after it reaches a
    terminal state.  Claimed drafts are intentionally outside this queryset.
    """
    from .models import Consent
    from .processing import cancel_deleted_draft_jobs

    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")
    now = timezone.now()
    outcome = {"purged": 0, "deferred": 0, "skipped": 0}
    files = []
    with transaction.atomic():
        drafts = list(GuestDraft.objects.select_for_update().select_related("owner", "machine").filter(
            claimed_by__isnull=True, expires_at__lte=now).order_by("expires_at", "pk")[:limit])
        for draft in drafts:
            machine = Machine.all_objects.select_for_update().get(pk=draft.machine_id)
            guest_owner = draft.owner
            # Claim locks GuestDraft before Machine.  Recheck every invariant
            # after both locks so a stale cleanup never touches another owner.
            if (draft.claimed_by_id or not guest_owner.is_guest or machine.owner_id != draft.owner_id):
                outcome["skipped"] += 1
                continue
            if machine.deleted_at is None:
                machine.deleted_at = now
                machine.revision += 1
                machine.save(update_fields=["deleted_at", "revision", "updated_at"])
            cancel_deleted_draft_jobs(machine)
            if machine.analysis_jobs.filter(status__in=["queued", "running"]).exists():
                outcome["deferred"] += 1
                continue
            # A visitor cannot create any of these, but preserve unexpected
            # historical/admin material instead of deleting beyond this scope.
            if (machine.versions.exists() or machine.submissions.exists() or machine.publications.exists()):
                outcome["skipped"] += 1
                continue
            assets = list(machine.assets.all())
            files.extend((field.storage, field.name) for asset in assets for field in (asset.original, asset.preview)
                         if field and field.name)
            Asset.objects.filter(machine=machine).delete()
            AnalysisJob.objects.filter(machine=machine).delete()
            # Consent is immutable to application users.  This controlled TTL
            # erasure is the one lifecycle exception and avoids retaining a
            # technical principal solely through a temporary AI consent.
            Consent.objects.filter(machine=machine)._raw_delete(using=machine._state.db)
            draft.delete()
            machine.delete()
            guest_owner.is_active = False
            guest_owner.save(update_fields=["is_active"])
            outcome["purged"] += 1

        def erase_files():
            for storage, name in files:
                try:
                    storage.delete(name)
                except Exception:
                    # Database cleanup remains durable, but an object-store
                    # failure must be visible to operations instead of being
                    # mistaken for a successful erasure.
                    logger.warning("Guest draft private storage cleanup failed.", exc_info=True)

        transaction.on_commit(erase_files)
    return outcome


def _secret_hash(value):
    return hashlib.sha256(f"{settings.SECRET_KEY}:guest-draft:{value}".encode()).hexdigest()


def _session_capability(request):
    value = request.session.get(SESSION_KEY)
    if not isinstance(value, dict):
        return None, None
    try:
        return uuid.UUID(str(value.get("id"))), value.get("secret")
    except (ValueError, TypeError, AttributeError):
        return None, None


def _clear_capability(request):
    request.session.pop(SESSION_KEY, None)


def _grant_capability(request, draft, secret):
    request.session.cycle_key()
    request.session[SESSION_KEY] = {"id": str(draft.pk), "secret": secret}


def _draft_for_request(request, pk=None, *, lock=False):
    capability_id, secret = _session_capability(request)
    if not capability_id or not isinstance(secret, str) or (pk is not None and capability_id != pk):
        raise PermissionDenied("El borrador temporal no está disponible en esta sesión.")
    query = GuestDraft.objects.select_related("machine", "owner")
    if lock:
        query = query.select_for_update()
    try:
        draft = query.get(pk=capability_id)
    except GuestDraft.DoesNotExist as exc:
        _clear_capability(request)
        raise PermissionDenied("El borrador temporal no está disponible.") from exc
    if not hmac.compare_digest(draft.secret_hash, _secret_hash(secret)):
        _clear_capability(request)
        raise PermissionDenied("El borrador temporal no está disponible en esta sesión.")
    if draft.claimed_by_id:
        _clear_capability(request)
        raise PermissionDenied("El borrador ya fue conservado en una cuenta.")
    if draft.expired:
        _clear_capability(request)
        raise GuestExpired("El borrador temporal venció. Puedes iniciar uno nuevo.")
    if not draft.owner.is_guest or draft.machine.owner_id != draft.owner_id:
        raise PermissionDenied("El borrador temporal no está disponible.")
    return draft


def _json(request, allowed):
    import json
    try:
        value = json.loads(request.body or "{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("El contenido de la solicitud no es válido.") from exc
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValidationError("La solicitud contiene campos no permitidos.")
    return value


def _initial_values(body):
    category = None
    category_id = body.get("category")
    if category_id not in (None, "", "unsure"):
        try:
            category = Category.objects.get(pk=category_id, active=True)
        except (Category.DoesNotExist, ValueError, TypeError) as exc:
            raise ValidationError("Selecciona un tipo disponible o «No estoy seguro».") from exc
    limits = {"serial": 150, "brand": 100, "model": 100, "description": 10000}
    data, provenance = {"currency": "USD"}, {"currency": {"source": "system", "review": "needs_review"}}
    for key, limit in limits.items():
        value = body.get(key, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ValidationError("Revisa los datos declarados.")
        value = value.strip()[:limit]
        if value:
            data[key] = value
            provenance[key] = {"source": "user", "review": "confirmed", "confidence": "owner_declared"}
    if category:
        provenance["category"] = {"source": "user", "review": "confirmed", "confidence": "owner_declared"}
    return category, data, provenance


def guest_state(draft):
    machine = draft.machine
    return {
        "id": str(draft.pk),
        "machine_id": str(machine.pk),
        "revision": machine.revision,
        "title": machine.title,
        "category": machine.category_id,
        "data": machine.data,
        "provenance": machine.provenance,
        "expires_at": draft.expires_at.isoformat(),
        "limits": {"max_images": MAX_GUEST_IMAGES, "max_analysis_jobs": MAX_GUEST_JOBS},
    }


def asset_state(asset):
    draft_id = asset.machine.guest_draft.pk
    return {"id": str(asset.pk), "url": f"/api/invitados/{draft_id}/archivos/{asset.pk}/", "kind": asset.kind,
            "purpose": asset.purpose, "is_cover": asset.is_cover, "processing_status": asset.processing_status,
            "error": asset.error, "position": asset.position}


def analysis_state(job, machine):
    # Keep the document shape identical to the authenticated wizard.  The
    # guest wrapper is separate so its UUID can never be confused with a
    # Machine UUID by a later claimed session.
    from .views import machine_state
    result = job.result if job.status == "completed" else None
    if isinstance(result, dict):
        result = {key: value for key, value in result.items() if key != "photo_cache"}
    return {"id": str(job.pk), "status": job.status, "result": result,
            "processing_stage": job.result.get("progress", {}).get("stage", job.status),
            "processing_progress": job.result.get("progress", {"stage": job.status}),
            "error": job.error if job.status == "failed" else "",
            "assets": [asset_state(asset) for asset in machine.assets.all()], "machine": machine_state(machine),
            "guest_draft": guest_state(machine.guest_draft),
            "auto_apply": services.automatic_application_status(job)}


def _response_error(exc):
    status = 410 if isinstance(exc, GuestExpired) else 403 if isinstance(exc, PermissionDenied) else 400
    return JsonResponse({"error": " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)}, status=status)


@ensure_csrf_cookie
@require_GET
def wizard(request, pk):
    """Render the normal wizard with a guest-scoped API base."""
    try:
        from .category_profiles import category_catalog
        from .views import machine_state
        draft = _draft_for_request(request, pk)
        machine = draft.machine
        models = (EquipmentModel.objects.filter(active=True, brand__active=True)
                  .filter(Q(category__isnull=True) | Q(category__active=True))
                  .select_related("brand"))
        catalog_models = [{"name": item.name, "brand": item.brand.name, "category": item.category_id} for item in models]
        job = AnalysisJob.objects.filter(machine=machine).order_by("-created_at").first()
        return render(request, "portal/wizard.html", {
            "machine": machine, "can_delete_draft": False, "assets": machine.assets.all(),
            "categories": Category.objects.filter(active=True),
            "categories_json": category_catalog(Category.objects.filter(active=True)),
            "catalog_brands": Brand.objects.filter(active=True),
            "catalog_models_json": catalog_models, "step": 1, "job": job, "data": machine.data,
            "provenance": machine.provenance, "machine_json": machine_state(machine),
            "guest_draft": guest_state(draft), "guest_api_base": f"/api/invitados/{draft.pk}/",
            # The shared wizard reads this context for its client-side upload
            # guard.  Keep the visitor display limit aligned with the server,
            # while retaining the platform's file-size validation values.
            "settings_context": {"max_images": MAX_GUEST_IMAGES,
                                 "max_image_mb": PlatformSettings.load().max_image_mb,
                                 "max_video_mb": PlatformSettings.load().max_video_mb,
                                 "max_video_seconds": PlatformSettings.load().max_video_seconds},
        })
    except (ValidationError, PermissionDenied):
        raise Http404


@require_POST
def start(request):
    try:
        form_post = request.content_type not in {"application/json", "application/json; charset=utf-8"}
        body = ({key: request.POST.get(key, "") for key in ("category", "serial", "brand", "model", "description")}
                if form_post else _json(request, {"category", "serial", "brand", "model", "description"}))
        if request.user.is_authenticated:
            return JsonResponse({"error": "Tu sesión ya puede conservar el borrador."}, status=409)
        existing_id, _ = _session_capability(request)
        if existing_id:
            try:
                existing = _draft_for_request(request, existing_id)
                return redirect("guest_wizard", pk=existing.pk) if form_post else JsonResponse(guest_state(existing))
            except (PermissionDenied, GuestExpired):
                pass
        if not throttle(request, "guest-draft-start", 3, 86400):
            raise ValidationError("Alcanzaste el límite de borradores temporales para hoy.")
        category, data, provenance = _initial_values(body)
        with transaction.atomic():
            identifier = secrets.token_hex(20)
            owner = User.objects.create_user(email=f"guest-{identifier}@temporary.invalid", password=None,
                                              is_guest=True, is_test=True, is_active=True)
            machine = Machine.objects.create(owner=owner, category=category, data=data, provenance=provenance)
            secret = secrets.token_urlsafe(32)
            draft = GuestDraft.objects.create(owner=owner, machine=machine, secret_hash=_secret_hash(secret))
        _grant_capability(request, draft, secret)
        if form_post:
            return redirect("guest_wizard", pk=draft.pk)
        return JsonResponse({**guest_state(draft), "url": f"/invitados/{draft.pk}/"}, status=201)
    except (ValidationError, PermissionDenied) as exc:
        return _response_error(exc)


@require_GET
def detail(request, pk):
    try:
        return JsonResponse(guest_state(_draft_for_request(request, pk)))
    except (ValidationError, PermissionDenied) as exc:
        return _response_error(exc)


@require_POST
def save(request, pk):
    try:
        draft = _draft_for_request(request, pk)
        body = _json(request, {"title", "category", "data", "provenance", "revision"})
        # ``revision`` is transport metadata, not a Machine payload field.
        # Keep the guest API equivalent to the authenticated save endpoint.
        revision = body.pop("revision", None)
        machine = services.save_draft(draft.machine, draft.owner, body, revision)
        draft.refresh_from_db()
        draft.machine.refresh_from_db()
        return JsonResponse({"revision": machine.revision, "saved_at": machine.updated_at.isoformat(),
                             "machine": guest_state(draft)})
    except (ValidationError, PermissionDenied) as exc:
        return _response_error(exc)


@require_POST
def upload(request, pk):
    try:
        from .processing import IMAGE_EXTENSIONS, ingest_asset
        uploaded = request.FILES.get("file")
        if not uploaded:
            raise ValidationError("Selecciona un archivo.")
        suffix = Path(uploaded.name or "").suffix.lower()
        content_type = (uploaded.content_type or "").lower()
        if suffix not in IMAGE_EXTENSIONS or not content_type.startswith("image/"):
            raise ValidationError("El borrador temporal sólo admite fotografías JPG, PNG, WEBP o HEIC.")
        purpose = request.POST.get("purpose", "general")
        if purpose not in {"general", "plate", "detail"}:
            raise ValidationError("El borrador temporal sólo admite fotografías de la maquinaria o de su placa.")
        draft = _draft_for_request(request, pk)
        # Rate limiting can run before the database lock; the definitive media
        # limit cannot.  GuestDraft then Machine use the same lock order as
        # claim/expiry, so simultaneous uploads cannot both consume slot 3.
        if not throttle(request, "guest-upload", 6, 86400, str(draft.pk)):
            raise ValidationError("Alcanzaste el límite de cargas temporales.")
        with transaction.atomic():
            draft = _draft_for_request(request, pk, lock=True)
            machine = Machine.objects.select_for_update().get(pk=draft.machine_id)
            if machine.assets.count() >= MAX_GUEST_IMAGES:
                raise ValidationError("El borrador temporal admite hasta tres fotografías. Regístrate para conservar y agregar más.")
            asset = ingest_asset(machine, draft.owner, uploaded, purpose)
            machine.refresh_from_db(fields=["revision"])
        return JsonResponse({**asset_state(asset), "revision": machine.revision}, status=201)
    except (ValidationError, PermissionDenied) as exc:
        return _response_error(exc)


@require_POST
def analyze(request, pk):
    try:
        from .processing import enqueue_analysis
        body = _json(request, {"consent", "asset_ids", "revision", "research", "mode", "auto_apply"})
        if body.get("consent") is not True:
            raise ValidationError("Autoriza el procesamiento de las fotografías necesarias mediante OpenAI.")
        # Hold the capability record and its Machine until the job exists.
        # This follows claim/expiry's GuestDraft -> Machine lock order, so two
        # requests with different revisions/options cannot both pass the one-
        # job guest budget and reserve paid analysis work.
        with transaction.atomic():
            draft = _draft_for_request(request, pk, lock=True)
            machine = Machine.objects.select_for_update().get(pk=draft.machine_id)
            if AnalysisJob.objects.filter(machine=machine).count() >= MAX_GUEST_JOBS:
                raise ValidationError("Este borrador temporal ya usó su análisis. Regístrate para continuar con más revisiones.")
            selected = body.get("asset_ids")
            if selected is not None and (not isinstance(selected, list) or len(selected) > MAX_GUEST_IMAGES):
                raise ValidationError("Selecciona hasta tres fotografías.")
            has_images = machine.assets.filter(kind="image", processing_status="ready").exclude(purpose="document").exists()
            declared = {key: value for key, value in machine.data.items() if key != "currency" and value not in (None, "")}
            if not has_images and not declared:
                raise ValidationError("Escribe marca, modelo, serie o una breve descripción antes de preparar la ficha sin fotografías.")
            requested_mode = body.get("mode") or ("analysis" if has_images else "description")
            if requested_mode not in {"analysis", "description"}:
                raise ValidationError("Este borrador aún no puede usar ese tipo de análisis.")
            # A client can keep its last visual-mode selection while the visitor
            # removes the final photo.  Safely downgrade that request to the
            # declared-data path instead of blocking a useful manual result.
            mode = requested_mode if has_images else "description"
            if body.get("auto_apply", True) is not True:
                raise ValidationError("El borrador temporal sólo puede aplicar propuestas automáticamente.")
            # A declared model without photos still deserves a useful, bounded
            # result.  It uses the normal description/research path, never makes
            # up a visual identification.
            research = body.get("research", not has_images)
            if type(research) is not bool:
                raise ValidationError("Indica si deseas consultar referencias públicas.")
            job = enqueue_analysis(machine, draft.owner, selected, mode, auto_apply=True,
                                   expected_revision=body.get("revision"), authorize_ai=True, research=research)
        return JsonResponse(analysis_state(job, machine))
    except (ValidationError, PermissionDenied) as exc:
        return _response_error(exc)


@require_GET
def analysis(request, pk, job_pk):
    try:
        draft = _draft_for_request(request, pk)
        job = AnalysisJob.objects.get(pk=job_pk, machine=draft.machine)
        draft.machine.refresh_from_db()
        return JsonResponse(analysis_state(job, draft.machine))
    except AnalysisJob.DoesNotExist:
        return JsonResponse({"error": "El análisis no está disponible."}, status=404)
    except (ValidationError, PermissionDenied) as exc:
        return _response_error(exc)


@require_GET
def asset(request, pk, asset_pk):
    try:
        draft = _draft_for_request(request, pk)
        record = Asset.objects.get(pk=asset_pk, machine=draft.machine)
        field = record.original if request.GET.get("original") == "1" or not record.preview else record.preview
        if not field:
            raise Http404
        content_type = record.mime_type if field == record.original else ("video/mp4" if record.kind == "video" else "image/jpeg")
        response = FileResponse(field.open("rb"), content_type=content_type)
        response["Cache-Control"] = "private, no-store"
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
    except Asset.DoesNotExist:
        raise Http404
    except (ValidationError, PermissionDenied) as exc:
        return _response_error(exc)


@require_POST
def asset_action(request, pk, asset_pk):
    try:
        draft = _draft_for_request(request, pk)
        body = _json(request, {"action", "purpose"})
        with transaction.atomic():
            machine = Machine.objects.select_for_update().get(pk=draft.machine_id)
            record = Asset.objects.select_for_update().get(pk=asset_pk, machine=machine)
            action = body.get("action")
            if action == "delete":
                if machine.analysis_jobs.exists():
                    raise ValidationError("No puedes retirar archivos después del análisis temporal. Regístrate para continuar con una nueva revisión.")
                record.delete()
            elif action == "cover":
                if record.kind != "image":
                    raise ValidationError("La portada debe ser una fotografía.")
                machine.assets.update(is_cover=False)
                record.is_cover = True
                record.save(update_fields=["is_cover"])
            elif action in {"up", "down"}:
                if machine.analysis_jobs.exists():
                    raise ValidationError("No puedes reordenar archivos después del análisis temporal. Regístrate para continuar con una nueva revisión.")
                items = list(machine.assets.order_by("position", "created_at"))
                index = next(index for index, item in enumerate(items) if item.pk == record.pk)
                target = max(0, min(len(items) - 1, index + (-1 if action == "up" else 1)))
                items[index], items[target] = items[target], items[index]
                for position, item in enumerate(items):
                    item.position = position
                    item.save(update_fields=["position"])
            elif action == "purpose":
                purpose = body.get("purpose")
                if purpose not in {"general", "plate", "detail"}:
                    raise ValidationError("Tipo de fotografía no válido.")
                record.purpose = purpose
                record.public_authorized = False
                record.save(update_fields=["purpose", "public_authorized"])
            else:
                raise ValidationError("Acción no válida.")
            machine.revision += 1
            machine.save(update_fields=["revision", "updated_at"])
        return JsonResponse({"ok": True, "revision": machine.revision,
                             "assets": [asset_state(item) for item in machine.assets.all()]})
    except Asset.DoesNotExist:
        raise Http404
    except (ValidationError, PermissionDenied) as exc:
        return _response_error(exc)


def claim_after_authentication(request, user):
    """Atomically transfer the one existing Machine after login or register.

    A running job deliberately keeps its guest requester.  Its automatic apply
    guard sees the owner change and skips writes; completed evidence remains
    readable to the newly authenticated owner through the normal API.
    """
    if not user or not user.is_authenticated or user.is_guest:
        return None
    draft_id, secret = _session_capability(request)
    if not draft_id or not isinstance(secret, str):
        return None
    with transaction.atomic():
        try:
            draft = GuestDraft.objects.select_for_update().select_related("owner", "machine").get(pk=draft_id)
        except GuestDraft.DoesNotExist:
            _clear_capability(request)
            return None
        if not hmac.compare_digest(draft.secret_hash, _secret_hash(secret)) or draft.expired:
            _clear_capability(request)
            return None
        if draft.claimed_by_id:
            _clear_capability(request)
            return draft.machine_id if draft.claimed_by_id == user.pk else None
        machine = Machine.objects.select_for_update().get(pk=draft.machine_id)
        if machine.owner_id != draft.owner_id or not draft.owner.is_guest:
            _clear_capability(request)
            return None
        machine.owner = user
        machine.save(update_fields=["owner", "updated_at"])
        draft.claimed_by = user
        draft.claimed_at = timezone.now()
        draft.save(update_fields=["claimed_by", "claimed_at", "updated_at"])
        services.audit(user, "guest_draft.claimed", machine, {"guest_draft_id": str(draft.pk)})
    _clear_capability(request)
    return machine.pk
