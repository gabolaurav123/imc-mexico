"""Revocable owner-authorized web links, separate from catalogue publication."""
from copy import deepcopy
import logging
from types import SimpleNamespace
import base64
import uuid
from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods

from . import services
from .intake import assessed_photo_states, has_completed_preparation, preparation_mode, require_consistent_photos
from .models import Asset, Machine, PreparedShare, prepared_share_code
from .public_data import public_json
from .security import throttle
from .views import api, payload


logger = logging.getLogger(__name__)


def share_url(share):
    return f"{settings.PUBLIC_URL.rstrip('/')}/s/{share.code}/"


def legacy_share_url(token):
    code = base64.urlsafe_b64encode(token.bytes).decode('ascii').rstrip('=')
    return f"{settings.PUBLIC_URL.rstrip('/')}/s/{code}/"


def _legacy_token(code):
    # Lossless short alias, never a new publication or a weaker identifier.
    if len(code) != 22:
        return None
    try:
        decoded = base64.b64decode(code + '==', altchars=b'-_', validate=True)
        token = uuid.UUID(bytes=decoded)
        if legacy_share_url(token).rstrip('/').rsplit('/', 1)[-1] == code:
            return token
    except (ValueError, TypeError):
        pass
    raise Http404


def current_share(machine):
    return PreparedShare.objects.filter(machine=machine, enabled=True, revision=machine.revision,
        authorized_by_id=machine.owner_id).first()


def _locked_machine_query():
    """Lock only Machine when its optional category is joined.

    PostgreSQL rejects ``FOR UPDATE`` on the nullable side of the category's
    outer join.  The owner and category are still selected for the snapshot,
    but ``OF self`` makes the lock explicit on backends that support it.
    """
    options = {"of": ("self",)} if connection.features.has_select_for_update_of else {}
    return Machine.objects.select_for_update(**options).select_related("owner", "category")


def _share_json_boundary(view):
    """Keep an unexpected sharing failure actionable to the browser and logged."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except Exception:
            logger.exception("Unexpected failure while preparing a share link")
            return JsonResponse({"error": "No se pudo preparar el enlace. Inténtalo de nuevo; si continúa, avisa a IMC México."}, status=500)
    return wrapped


def _safe_assets(machine):
    states = assessed_photo_states(machine)
    plate_ids = services.detected_plate_asset_ids(machine)
    assets = list(machine.assets.filter(kind="image", purpose__in=["general", "detail"],
        processing_status="ready").exclude(pk__in=plate_ids).order_by("-is_cover", "position", "created_at"))
    return [asset for asset in assets if states.get(str(asset.pk)) == "accepted" or asset.public_authorized]


@require_http_methods(["GET", "POST"])
@_share_json_boundary
@api
def manage(request, pk):
    # Being staff or knowing an ID never substitutes for the owner's consent.
    machine = get_object_or_404(Machine.objects.select_related("owner", "category"), pk=pk, owner=request.user)
    if request.user.is_guest:
        raise PermissionDenied
    if request.method == "GET":
        share = PreparedShare.objects.filter(machine=machine, authorized_by_id=machine.owner_id).first()
        active = bool(share and share.enabled and share.revision == machine.revision)
        return JsonResponse({"url": share_url(share) if active else "", "enabled": active,
                             "revision": machine.revision, "include_serial": bool(share and share.include_serial),
                             "include_contact": bool(share and share.snapshot.get("contact_authorized"))})
    body = payload(request, ["revision", "action", "include_serial", "include_contact", "asset_ids"])
    if body.get("action", "enable") not in {"enable", "disable"}:
        raise ValidationError("Acción de compartir no válida.")
    if "include_serial" in body and type(body["include_serial"]) is not bool:
        raise ValidationError("Indica si autorizas mostrar el número de serie.")
    if "include_contact" in body and type(body["include_contact"]) is not bool:
        raise ValidationError("Indica si autorizas mostrar tu contacto.")
    if not throttle(request, "prepared-share", 40, 3600, str(request.user.pk)):
        raise ValidationError("Espera un momento antes de volver a preparar el enlace.")
    with transaction.atomic():
        machine = _locked_machine_query().get(pk=machine.pk)
        if machine.owner_id != request.user.pk:
            raise PermissionDenied
        if type(body.get("revision")) is not int or machine.revision != body["revision"]:
            raise services.DraftRevisionConflict("La ficha cambió. Guarda los cambios antes de compartirla.")
        share = PreparedShare.objects.select_for_update().filter(machine=machine).first()
        if body.get("action") == "disable":
            if share:
                share.enabled = False
                # Revoked URLs stay revoked even when the owner shares again.
                share.code = prepared_share_code()
                share.save(update_fields=["enabled", "code", "updated_at"])
                services.audit(request.user, "prepared_share.disabled", machine)
            return JsonResponse({"url": "", "enabled": False, "revision": machine.revision})
        if not request.user.is_active or request.user.advertiser_status in {"suspended", "rejected"}:
            raise PermissionDenied
        if machine.availability == "withdrawn" or machine.status in {"rejected", "cancelled"}:
            raise ValidationError("Esta ficha no está disponible para compartir.")
        if not machine.category_id or not any(machine.data.get(key) for key in ("brand", "model", "description")):
            raise ValidationError("Genera la ficha de maquinaria antes de compartirla.")
        mode = preparation_mode(machine)
        completed_preparation = has_completed_preparation(machine)
        require_consistent_photos(machine)
        eligible = {str(asset.pk): asset for asset in _safe_assets(machine)}
        requested = body.get("asset_ids")
        if requested is not None:
            if (not isinstance(requested, list) or len(requested) > 10 or len(set(map(str, requested))) != len(requested)
                    or any(str(pk) not in eligible for pk in requested)):
                raise ValidationError("Selecciona hasta diez fotografías de maquinaria analizadas; las placas y documentos son privados.")
            ids = list(map(str, requested))
        else:
            ids = list(eligible)[:10]
        pending = machine.assets.filter(kind="image", purpose__in=["general", "detail"], processing_status="ready")
        if requested is None and any(str(asset.pk) not in eligible and str(asset.pk) not in services.detected_plate_asset_ids(machine) for asset in pending):
            raise ValidationError("Genera la ficha con las nuevas fotografías antes de compartirlas; todavía no se ha comprobado que correspondan a maquinaria.")
        if not completed_preparation and (mode == "analysis" or not machine.approved_version_id):
            raise ValidationError("Genera la ficha de maquinaria antes de compartirla.")
        raw = {"data": machine.data, "provenance": machine.provenance, "title": machine.title}
        projected = public_json(raw, title=machine.title)
        include_serial = body.get("include_serial", share.include_serial if share else False)
        safe_data = projected["data"]
        if include_serial and machine.data.get("serial"):
            safe_data["serial"] = str(machine.data["serial"])[:150]
        include_contact = body.get("include_contact", bool(share and share.snapshot.get("contact_authorized")))
        if include_contact:
            declared = machine.data.get("contact_public")
            if isinstance(declared, str) and declared.strip():
                safe_data["contact_public"] = declared.strip()[:600]
            else:
                # Only the explicitly chosen channel, never the entire profile.
                if request.user.contact_preference == "email":
                    safe_data["contact_public"] = f"Correo: {request.user.email}"
                elif request.user.phone:
                    label = "WhatsApp" if request.user.contact_preference == "whatsapp" else "Teléfono"
                    safe_data["contact_public"] = f"{label}: {request.user.phone}"
            include_contact = bool(safe_data.get("contact_public"))
        snapshot = {"title": projected["title"] or "Maquinaria", "category": machine.category_id,
            "category_name": machine.category.name, "data": deepcopy(safe_data), "provenance": {},
            "public_asset_ids": ids, "asset_ids": ids, "private_plate_asset_ids": [],
            "contact_authorized": include_contact, "revision": machine.revision}
        if share is None:
            share = PreparedShare(machine=machine, authorized_by=request.user, revision=machine.revision)
        elif not share.enabled or share.authorized_by_id != request.user.pk:
            share.code = prepared_share_code()
        share.authorized_by = request.user
        share.enabled, share.revision, share.snapshot, share.include_serial = True, machine.revision, snapshot, include_serial
        share.save()
        services.audit(request.user, "prepared_share.enabled", machine,
            {"revision": machine.revision, "asset_ids": ids, "include_serial": include_serial,
             "include_contact": include_contact})
    return JsonResponse({"url": share_url(share), "enabled": True, "revision": machine.revision,
                         "include_serial": include_serial, "include_contact": include_contact})


def record(code):
    share = get_object_or_404(PreparedShare.objects.select_related("machine", "machine__owner", "machine__category"),
        code=code, enabled=True, machine__deleted_at__isnull=True)
    machine = share.machine
    if (share.authorized_by_id != machine.owner_id or share.revision != machine.revision
            or not machine.owner.is_active or machine.owner.is_guest
            or machine.owner.advertiser_status in {"suspended", "rejected"}
            or machine.status in {"rejected", "cancelled"} or machine.availability == "withdrawn"):
        raise Http404
    try:
        require_consistent_photos(machine)
    except ValidationError:
        raise Http404
    return share


def snapshot_assets(share):
    eligible = {str(asset.pk): asset for asset in _safe_assets(share.machine)}
    return [eligible[pk] for pk in share.snapshot.get("public_asset_ids", []) if pk in eligible]


@require_GET
def sheet(request, code):
    from .views import sheet_context
    legacy_token = _legacy_token(code)
    if legacy_token is not None:
        from .views import public_sheet
        return public_sheet(request, legacy_token)
    share = record(code)
    version = SimpleNamespace(data=share.snapshot, number=share.revision, created_at=share.updated_at)
    context = sheet_context(share.machine, version, public=True, token=code)
    assets = snapshot_assets(share)
    context.update({"assets": assets, "main_assets": assets[:4], "additional_assets": assets[4:10],
        "asset_base_url": f"/s/{code}/archivo/", "share_url": share_url(share),
        "catalog_back": "https://www.imcmexico.com.mx/catalogo-de-maquinaria", "can_export": False,
        "share_contact_url": f"/contacto/?maquinaria={share.machine_id}&share={code}",
        "prepared_share": True, "public_serial_authorized": share.include_serial})
    if share.include_serial and share.snapshot.get("data", {}).get("serial"):
        context["data"]["serial"] = share.snapshot["data"]["serial"]
    if share.snapshot.get("contact_authorized") and share.snapshot.get("data", {}).get("contact_public"):
        context["data"]["contact_public"] = share.snapshot["data"]["contact_public"]
    response = render(request, "portal/sheet.html", context)
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_GET
def asset(request, code, pk):
    from .views import send_asset
    legacy_token = _legacy_token(code)
    if legacy_token is not None:
        from .views import public_asset
        return public_asset(request, legacy_token, pk)
    share = record(code)
    candidate = next((asset for asset in snapshot_assets(share) if asset.pk == pk), None)
    if candidate is None:
        raise Http404
    return send_asset(candidate)
