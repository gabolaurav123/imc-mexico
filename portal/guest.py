"""Short-lived visitor draft capability.

Visitors never authenticate as the technical owner.  The browser receives an
opaque session capability, while the normal Machine/Asset/AnalysisJob models
continue to own all saved work.  A successful account login atomically changes
the machine owner to the real account.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from . import services
from .models import AnalysisJob, Asset, Brand, Category, EquipmentModel, GuestDraft, GuestTrial, Machine, PlatformSettings, PreparedShare, User, prepared_share_code
from .security import throttle

SESSION_KEY = "guest_draft_capability"
BROWSER_COOKIE = "guest_browser_id"
BROWSER_COOKIE_AGE = 60 * 60 * 24 * 400
MAX_GUEST_IMAGES = 4
MAX_GUEST_JOBS = 1
MAX_GUEST_SERVICE_RETRIES = 3
RETRIABLE_SERVICE_FAILURE_CODES = frozenset({"billing_unavailable", "credentials_unavailable", "model_unavailable"})
logger = logging.getLogger(__name__)


class GuestExpired(ValidationError):
    pass


class GuestQuotaExceeded(ValidationError):
    pass


def _trusted_proxy_networks():
    """Return valid configured proxy ranges; a bad setting fails closed."""
    networks = []
    for value in getattr(settings, "TRUSTED_PROXY_CIDRS", ()):
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid TRUSTED_PROXY_CIDRS entry.")
    return tuple(networks)


def _client_ip(request):
    """Resolve an address only when the immediate peer is a trusted proxy.

    ``X-Forwarded-For`` is client-to-proxy ordered.  Starting at its right
    edge prevents an attacker from choosing the left-most value when a chain
    contains more than one trusted proxy.  If anything is malformed, use the
    direct peer rather than an untrusted header.
    """
    peer_value = request.META.get("REMOTE_ADDR", "")
    try:
        peer = ipaddress.ip_address(peer_value)
    except ValueError:
        return None
    networks = _trusted_proxy_networks()
    if not networks or not any(peer in network for network in networks):
        return _normalized_ip(peer)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if not forwarded:
        return _normalized_ip(peer)
    try:
        chain = [ipaddress.ip_address(value.strip()) for value in forwarded.split(",")]
    except ValueError:
        return _normalized_ip(peer)
    if not chain:
        return peer.compressed
    for address in reversed(chain):
        if not any(address in network for network in networks):
            return _normalized_ip(address)
    return _normalized_ip(chain[0])


def _normalized_ip(address):
    """Treat an IPv4 address and its IPv4-mapped IPv6 form as one address."""
    return address.ipv4_mapped.compressed if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped else address.compressed


def _guest_browser_token(request):
    """Issue a random, HttpOnly browser marker independent of login sessions."""
    value = request.COOKIES.get(BROWSER_COOKIE)
    if not isinstance(value, str) or len(value) < 32:
        value = secrets.token_urlsafe(32)
        request._guest_browser_cookie = value
    return value


def _with_browser_cookie(request, response):
    value = getattr(request, "_guest_browser_cookie", None)
    if value:
        response.set_cookie(BROWSER_COOKIE, value, max_age=BROWSER_COOKIE_AGE, httponly=True,
                            secure=not settings.DEBUG, samesite="Lax")
    return response


def _guest_trial_identity(request):
    client_ip = _client_ip(request)
    if client_ip is None:
        raise ValidationError("No pudimos verificar la conexión para iniciar la ficha temporal.")
    # Separate purpose labels make a digest non-reusable across data domains.
    key = settings.SECRET_KEY.encode()
    ip_hash = hmac.new(key, f"guest-trial-ip:{client_ip}".encode(), hashlib.sha256).hexdigest()
    browser_hash = hmac.new(key, f"guest-trial-browser:{_guest_browser_token(request)}".encode(),
                            hashlib.sha256).hexdigest()
    return ip_hash, browser_hash


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
            # A visitor shortlink is temporary capability-derived output, not
            # a historical publication. Remove it before deleting the Machine
            # which PreparedShare otherwise protects.
            PreparedShare.objects.filter(machine=machine, guest_share=True).delete()
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
        raise GuestExpired("El borrador temporal venció. Crea una cuenta para continuar.")
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
    from .technical_description import description_projection
    share = PreparedShare.objects.filter(
        machine=machine, enabled=True, guest_share=True, authorized_by_id=draft.owner_id,
        revision=machine.revision, guest_expires_at__gt=timezone.now(),
    ).first()
    return {
        "id": str(draft.pk),
        "machine_id": str(machine.pk),
        "revision": machine.revision,
        "title": machine.title,
        "category": machine.category_id,
        "data": description_projection(machine.data, machine.provenance,
                                       category=machine.category.name if machine.category_id else None),
        "provenance": machine.provenance,
        "expires_at": draft.expires_at.isoformat(),
        "limits": {"max_images": MAX_GUEST_IMAGES, "max_analysis_jobs": MAX_GUEST_JOBS,
                   "max_service_retries": MAX_GUEST_SERVICE_RETRIES},
        "analysis_used": _guest_analysis_used(machine),
        "serial_enrichment_available": _serial_enrichment_available(machine),
        "share": {"enabled": bool(share),
                  "url": f"{settings.PUBLIC_URL.rstrip('/')}/s/{share.code}/" if share else ""},
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
    from .intake import preparation_completeness
    result = job.result if job.status == "completed" else None
    if isinstance(result, dict):
        result = {key: value for key, value in result.items() if key != "photo_cache"}
    failure_code = job.result.get("provider_error_code", "") if job.status == "failed" and isinstance(job.result, dict) else ""
    if failure_code not in RETRIABLE_SERVICE_FAILURE_CODES:
        failure_code = ""
    return {"id": str(job.pk), "status": job.status, "failure_code": failure_code, "result": result,
            "completion": preparation_completeness(machine, job) if job.status == "completed" else {},
            "processing_stage": job.result.get("progress", {}).get("stage", job.status),
            "processing_progress": job.result.get("progress", {"stage": job.status}),
            "error": job.error if job.status == "failed" else "",
            "assets": [asset_state(asset) for asset in machine.assets.all()], "machine": machine_state(machine),
            "guest_draft": guest_state(machine.guest_draft),
            "auto_apply": services.automatic_application_status(job)}


def _job_is_retriable_service_failure(job):
    return (job.status == "failed" and isinstance(job.result, dict)
            and job.result.get("provider_error_code") in RETRIABLE_SERVICE_FAILURE_CODES)


def _guest_analysis_used(machine):
    """A provider availability failure does not spend the visitor analysis."""
    return any(not _job_is_retriable_service_failure(job)
               for job in machine.analysis_jobs.only("status", "result"))


def _serial_enrichment_available(machine, jobs=None):
    """One serial supplement for the same already-checked visitor machine.

    The allowance is derived under the draft/machine locks when enqueueing. A
    queued supplement consumes it immediately, so concurrent browser events
    cannot reserve multiple paid jobs. Provider availability failures retain
    the existing bounded service-retry policy.
    """
    from .intake import has_written_serial
    serial = (machine.data or {}).get("serial")
    if not has_written_serial(serial):
        return False
    jobs = list(machine.analysis_jobs.all()) if jobs is None else list(jobs)
    if sum(_job_is_retriable_service_failure(job) for job in jobs) >= MAX_GUEST_SERVICE_RETRIES:
        return False
    consumed = [job for job in jobs if not _job_is_retriable_service_failure(job)]
    if len(consumed) != 1:
        return False
    original = consumed[0]
    result = original.result if isinstance(original.result, dict) else {}
    snapshot = result.get("input_snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("data"), dict):
        # Unknown historical inputs cannot establish that this is new evidence.
        return False
    previous = snapshot["data"]
    consistency = result.get("consistency", {})
    reading = result.get("data", {})
    if not all(isinstance(value, dict) for value in (previous, consistency, reading)):
        return False
    if (original.status != "completed" or original.mode != "analysis" or result.get("preflight")
            or result.get("blocking_reason") or consistency.get("status") == "contradiction"
            or has_written_serial(previous.get("serial")) or result.get("input_category_id") != machine.category_id):
        return False
    # An existing OCR serial does not warrant another paid run unless the
    # owner actually corrected it. Whitespace/case changes are not new data.
    normalize = lambda value: "".join(char for char in str(value or "").casefold() if char.isalnum())
    if normalize(serial) == normalize(reading.get("serial")):
        return False
    assets = services._analysis_asset_state(machine)
    if (not assets or len(assets) > MAX_GUEST_IMAGES
            or any(item["kind"] != "image" or item["status"] != "ready" for item in assets)
            or not isinstance(original.application_snapshot, dict)
            or services._analysis_snapshot_asset_state(original.application_snapshot.get("assets")) != assets):
        return False
    current_ids = {item["id"] for item in assets}
    relevance = result.get("relevance") or {}
    if (not isinstance(relevance, dict) or not isinstance(original.asset_ids, list)
            or not isinstance(relevance.get("accepted_asset_ids"), list)):
        return False
    return (current_ids == set(map(str, original.asset_ids))
            and relevance.get("status") == "relevant"
            and not relevance.get("excluded_asset_ids") and not relevance.get("uncertain_asset_ids")
            and current_ids <= set(map(str, relevance.get("accepted_asset_ids", []))))


def _response_error(exc):
    if isinstance(exc, GuestQuotaExceeded):
        return JsonResponse({
            "error": "Ya usaste el intento gratuito de esta conexión. Crea una cuenta para preparar y compartir más fichas.",
            "code": "guest_trial_used",
            "signup_url": "/registro/",
            "registration_url": "/registro/",
            "login_url": "/iniciar-sesion/",
        }, status=429)
    status = 410 if isinstance(exc, GuestExpired) else 403 if isinstance(exc, PermissionDenied) else 400
    return JsonResponse({"error": " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)}, status=status)


@ensure_csrf_cookie
@require_GET
def wizard(request, pk):
    """Render the normal wizard with a guest-scoped API base."""
    try:
        from .category_profiles import category_catalog
        from .intake import preparation_completeness
        from .views import machine_state
        draft = _draft_for_request(request, pk)
        machine = draft.machine
        # The start form already loads approved catalogue choices lazily.  Do
        # not serialize the entire catalogue into every guest wizard response.
        catalog_models = []
        job = AnalysisJob.objects.filter(machine=machine).order_by("-created_at").first()
        state = machine_state(machine)
        return render(request, "portal/wizard.html", {
            "machine": machine, "can_delete_draft": False, "assets": machine.assets.all(),
            "categories": Category.objects.filter(active=True),
            "categories_json": category_catalog(Category.objects.filter(active=True)),
            "catalog_brands": Brand.objects.filter(active=True),
            "catalog_models_json": catalog_models, "step": 1, "job": job, "data": state["data"],
            "provenance": machine.provenance, "machine_json": state,
            "preparation_completion": preparation_completeness(machine),
            "guest_draft": guest_state(draft), "guest_api_base": f"/api/invitados/{draft.pk}/",
            # ``guest_state`` is JSON-facing and uses ISO strings; keep a
            # real datetime alongside it for date formatting in the template.
            "guest_expires_at": draft.expires_at,
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


@require_GET
def preview(request, pk):
    """Private virtual-sheet preview for the visitor who holds the capability."""
    try:
        from .intake import preparation_completeness
        from .sharing import share_url
        from .views import sheet_context
        draft = _draft_for_request(request, pk)
        machine = draft.machine
        context = sheet_context(machine)
        active_share = PreparedShare.objects.filter(
            machine=machine, authorized_by_id=draft.owner_id, enabled=True, guest_share=True,
            revision=machine.revision, guest_expires_at__gt=timezone.now(),
        ).first()
        # Never use the normal owner asset URL here: the temporary principal
        # cannot log in, and the capability route is the only read authority.
        context.update({
            "assets": machine.assets.all(),
            "asset_base_url": f"/api/invitados/{draft.pk}/archivos/",
            "guest_preview": True,
            "guest_draft": guest_state(draft),
            "sheet_completion_data": {key: machine.data.get(key) for key in
                                      ("location", "location_country", "location_city", "hours")},
            "sheet_editor_url": f"/invitados/{draft.pk}/?paso=2",
            "sheet_share_endpoint": f"/api/invitados/{draft.pk}/compartir/",
            "share_url": share_url(active_share) if active_share else "",
            "guest_share_expires_at": draft.expires_at,
            "include_serial": bool(active_share and active_share.include_serial),
            "include_contact": False,
            "can_export": False,
            "preparation_completion": preparation_completeness(machine),
        })
        return render(request, "portal/sheet.html", context)
    except (ValidationError, PermissionDenied):
        raise Http404


@require_POST
def start(request):
    form_post = request.content_type not in {"application/json", "application/json; charset=utf-8"}
    try:
        allowed = {"category", "serial", "brand", "model", "description", "entry_mode", "catalogue_model",
                   "catalogue_manual_brand", "catalogue_manual_model"}
        body = ({key: request.POST.get(key, "") for key in allowed} if form_post else _json(request, allowed))
        if request.user.is_authenticated:
            return JsonResponse({"error": "Tu sesión ya puede conservar el borrador."}, status=409)
        existing_id, _ = _session_capability(request)
        if existing_id:
            try:
                existing = _draft_for_request(request, existing_id)
                return redirect("guest_wizard", pk=existing.pk) if form_post else JsonResponse(guest_state(existing))
            except (PermissionDenied, GuestExpired):
                pass
        category, data, provenance = _initial_values(body)
        entry_mode = body.get("entry_mode", "")
        title = None
        if entry_mode == "catalogue":
            if not category:
                raise ValidationError("Selecciona el tipo de máquina que quieres anunciar.")
            from .catalogue_intake import catalogue_proposal
            proposal = catalogue_proposal(category.pk, body.get("catalogue_model"))
            data = proposal["data"]
            provenance = {**proposal["provenance"], "title": proposal["title_provenance"],
                          "category": {"source": "user", "review": "confirmed"}}
            title = proposal["title"]
        elif entry_mode == "manual_identity":
            brand = str(body.get("catalogue_manual_brand", "")).strip()[:100]
            model = str(body.get("catalogue_manual_model", "")).strip()[:100]
            if not brand or not model:
                raise ValidationError("Escribe la marca y el modelo, o selecciona un modelo del catálogo.")
            data.update({"brand": brand, "model": model})
            provenance.update({"brand": {"source": "user", "review": "confirmed"},
                               "model": {"source": "user", "review": "confirmed"}})
        with transaction.atomic():
            ip_hash, browser_hash = _guest_trial_identity(request)
            # The database uniqueness constraint is the quota authority.  It
            # works across workers and survives session clearing, while the
            # transaction rolls it back when the actual draft cannot be made.
            existing = GuestTrial.objects.select_for_update().filter(
                Q(ip_hash=ip_hash) | Q(browser_hash=browser_hash)
            ).first()
            if existing:
                raise GuestQuotaExceeded("guest trial already used")
            try:
                # The savepoint lets an overlapping process win either unique
                # index without breaking the outer creation transaction.
                with transaction.atomic():
                    trial = GuestTrial.objects.create(ip_hash=ip_hash, browser_hash=browser_hash)
            except IntegrityError:
                raise GuestQuotaExceeded("guest trial already used")
            identifier = secrets.token_hex(20)
            owner = User.objects.create_user(email=f"guest-{identifier}@temporary.invalid", password=None,
                                              is_guest=True, is_test=True, is_active=True)
            machine = Machine.objects.create(owner=owner, category=category, data=data, provenance=provenance,
                                             **({"title": title} if title else {}))
            secret = secrets.token_urlsafe(32)
            draft = GuestDraft.objects.create(owner=owner, machine=machine, secret_hash=_secret_hash(secret))
            trial.draft = draft
            trial.save(update_fields=["draft", "updated_at"])
        _grant_capability(request, draft, secret)
        suffix = ("?entrada=catalogue&paso=1" if entry_mode == "catalogue" else
                  "?entrada=" + entry_mode if entry_mode in {"plate", "serial", "photos", "manual_identity"} else "")
        if form_post:
            return _with_browser_cookie(request, redirect(f"/invitados/{draft.pk}/{suffix}"))
        return _with_browser_cookie(request, JsonResponse({**guest_state(draft), "url": f"/invitados/{draft.pk}/{suffix}"}, status=201))
    except GuestQuotaExceeded as exc:
        if form_post:
            return render(request, "portal/guest_limit.html", {"signup_url": "/registro/", "login_url": "/iniciar-sesion/"}, status=429)
        return _response_error(exc)
    except (ValidationError, PermissionDenied) as exc:
        if form_post and isinstance(exc, ValidationError):
            from .category_profiles import category_catalog
            categories = Category.objects.filter(active=True)
            return render(request, "portal/start.html", {
                "guest_mode": True, "categories_json": category_catalog(categories),
                "error": " ".join(exc.messages),
            }, status=400)
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


@require_http_methods(["GET", "POST"])
def share(request, pk):
    """Prepare or revoke a short-lived, non-catalogue visitor link.

    This route accepts the same session capability as the private draft. It
    intentionally has no path to submit, publish, choose a contact channel,
    or mark media public. A fresh account can prepare its own owner link only
    after it claims the draft.
    """
    try:
        draft = _draft_for_request(request, pk)
        if request.method == "GET":
            share = PreparedShare.objects.filter(
                machine=draft.machine, authorized_by_id=draft.owner_id, guest_share=True,
            ).first()
            active = bool(share and share.enabled and share.revision == draft.machine.revision
                          and share.guest_expires_at and share.guest_expires_at > timezone.now())
            return JsonResponse({"url": f"{settings.PUBLIC_URL.rstrip('/')}/s/{share.code}/" if active else "",
                                 "enabled": active, "revision": draft.machine.revision,
                                 "include_serial": bool(active and share.include_serial),
                                 "include_contact": False, "expires_at": draft.expires_at.isoformat()})
        body = _json(request, {"revision", "action", "include_serial", "include_contact", "asset_ids"})
        if body.get("action", "enable") not in {"enable", "disable"}:
            raise ValidationError("Acción de compartir no válida.")
        if "include_serial" in body and type(body["include_serial"]) is not bool:
            raise ValidationError("Indica si autorizas mostrar el número de serie.")
        # A technical guest principal has no verified contact channel. Do not
        # accept contact data or an asset selection from the browser, even if
        # it was forged; plate images and contact never reach this snapshot.
        if body.get("include_contact") not in (None, False) or body.get("asset_ids") not in (None, []):
            raise ValidationError("La vista temporal no permite compartir contacto ni seleccionar archivos privados.")
        if not throttle(request, "guest-prepared-share", 20, 3600, str(draft.pk)):
            raise ValidationError("Espera un momento antes de volver a preparar el enlace.")
        with transaction.atomic():
            draft = _draft_for_request(request, pk, lock=True)
            machine = Machine.objects.select_for_update().select_related("category").get(pk=draft.machine_id)
            if type(body.get("revision")) is not int or machine.revision != body["revision"]:
                raise services.DraftRevisionConflict("La ficha cambió. Guarda los cambios antes de compartirla.")
            share = PreparedShare.objects.select_for_update().filter(machine=machine).first()
            if body.get("action") == "disable":
                if share and share.guest_share and share.authorized_by_id == draft.owner_id:
                    share.enabled = False
                    share.code = prepared_share_code()
                    share.save(update_fields=["enabled", "code", "updated_at"])
                    services.audit(draft.owner, "guest_prepared_share.disabled", machine)
                return JsonResponse({"url": "", "enabled": False, "revision": machine.revision})
            if not machine.category_id or not any(machine.data.get(key) for key in ("brand", "model", "description")):
                raise ValidationError("Genera la ficha de maquinaria antes de compartirla.")
            from .intake import has_completed_preparation, require_consistent_photos
            from .sharing import _safe_assets
            if not has_completed_preparation(machine):
                raise ValidationError("Genera la ficha de maquinaria antes de compartirla.")
            require_consistent_photos(machine)
            from .public_data import public_json
            projected = public_json({"data": machine.data, "provenance": machine.provenance,
                                     "title": machine.title, "category_name": machine.category.name},
                                    title=machine.title)
            safe_data = projected["data"]
            include_serial = body.get("include_serial", False)
            if include_serial and machine.data.get("serial"):
                safe_data["serial"] = str(machine.data["serial"])[:150]
            # _safe_assets already excludes detected plates. Keep the explicit
            # purpose filter as a second boundary for a future classifier bug.
            asset_ids = [str(asset.pk) for asset in _safe_assets(machine) if asset.purpose in {"general", "detail"}]
            snapshot = {"title": projected["title"] or "Maquinaria", "category": machine.category_id,
                        "category_name": machine.category.name, "data": safe_data, "provenance": {},
                        "public_asset_ids": asset_ids, "asset_ids": asset_ids, "private_plate_asset_ids": [],
                        "contact_authorized": False, "revision": machine.revision}
            if share is None:
                share = PreparedShare(machine=machine, authorized_by=draft.owner, revision=machine.revision)
            elif not share.enabled or not share.guest_share or share.authorized_by_id != draft.owner_id:
                share.code = prepared_share_code()
            share.authorized_by = draft.owner
            share.enabled, share.revision, share.snapshot = True, machine.revision, snapshot
            share.include_serial, share.guest_share, share.guest_expires_at = include_serial, True, draft.expires_at
            share.save()
            services.audit(draft.owner, "guest_prepared_share.enabled", machine,
                           {"revision": machine.revision, "asset_ids": asset_ids, "include_serial": include_serial})
        return JsonResponse({"url": f"{settings.PUBLIC_URL.rstrip('/')}/s/{share.code}/", "enabled": True,
                             "revision": machine.revision, "include_serial": include_serial,
                             "include_contact": False, "expires_at": draft.expires_at.isoformat()})
    except services.DraftRevisionConflict as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=409)
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
                raise ValidationError("El borrador temporal admite hasta cuatro fotografías. Regístrate para conservar y agregar más.")
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
            jobs = list(AnalysisJob.objects.filter(machine=machine))
            serial_supplement = _serial_enrichment_available(machine, jobs)
            if sum(_job_is_retriable_service_failure(job) for job in jobs) >= MAX_GUEST_SERVICE_RETRIES:
                raise ValidationError("El servicio no está disponible después de varios intentos. Regístrate para continuar más tarde.")
            if any(not _job_is_retriable_service_failure(job) for job in jobs) and not serial_supplement:
                raise ValidationError("Este borrador temporal ya usó su análisis. Regístrate para continuar con más revisiones.")
            selected = body.get("asset_ids")
            if selected is not None and (not isinstance(selected, list) or len(selected) > MAX_GUEST_IMAGES):
                raise ValidationError("Selecciona hasta cuatro fotografías.")
            if serial_supplement:
                checked_ids = {item["id"] for item in services._analysis_asset_state(machine)}
                if selected is not None and set(map(str, selected)) != checked_ids:
                    raise ValidationError("Conserva las fotografías de esta ficha para completar sus datos con la serie.")
            from .intake import preparation_mode
            mode = preparation_mode(machine, selected)
            requested_mode = body.get("mode") or mode
            if requested_mode not in {"analysis", "description"}:
                raise ValidationError("Este borrador aún no puede usar ese tipo de análisis.")
            if body.get("auto_apply", True) is not True:
                raise ValidationError("El borrador temporal sólo puede aplicar propuestas automáticamente.")
            # A typed serial without photos uses the bounded research path;
            # photographs always use visual analysis regardless of client mode.
            research = body.get("research", True)
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
                if _guest_analysis_used(machine):
                    raise ValidationError("No puedes retirar archivos después del análisis temporal. Regístrate para continuar con una nueva revisión.")
                record.delete()
            elif action == "cover":
                if record.kind != "image":
                    raise ValidationError("La portada debe ser una fotografía.")
                machine.assets.update(is_cover=False)
                record.is_cover = True
                record.save(update_fields=["is_cover"])
            elif action in {"up", "down"}:
                if _guest_analysis_used(machine):
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
        # A visitor authorization belongs to the short-lived technical
        # principal. Claiming starts an account-owned lifecycle, so an old
        # visitor URL must never silently become that account's public link.
        share = PreparedShare.objects.select_for_update().filter(machine=machine, guest_share=True).first()
        if share:
            share.enabled = False
            share.code = prepared_share_code()
            share.save(update_fields=["enabled", "code", "updated_at"])
        machine.owner = user
        machine.save(update_fields=["owner", "updated_at"])
        draft.claimed_by = user
        draft.claimed_at = timezone.now()
        draft.save(update_fields=["claimed_by", "claimed_at", "updated_at"])
        services.audit(user, "guest_draft.claimed", machine, {"guest_draft_id": str(draft.pk)})
    _clear_capability(request)
    return machine.pk
