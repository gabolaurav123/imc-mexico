"""Private, read-only machine document API for an authorized module frontend."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import math

from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse
from django.urls import reverse

from .models import Machine
from .security import staff_authorized


def _json_value(value):
    """Return only JSON values; do not let an unusual legacy value poison a response."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _can_read_machine(user):
    return bool(user.is_authenticated and user.is_active)


def _machine_for_reader(user, pk):
    queryset = Machine.objects.select_related("category", "approved_version").prefetch_related("assets")
    if not (staff_authorized(user) and user.has_perm("portal.view_machine")):
        queryset = queryset.filter(owner=user)
    return queryset.get(pk=pk)


def _private_response(value, status=200):
    response = JsonResponse(value, status=status, encoder=DjangoJSONEncoder,
                            json_dumps_params={"allow_nan": False})
    response["Cache-Control"] = "private, no-store"
    response["Vary"] = "Cookie"
    return response


def _asset_document(asset):
    # A FileField name is a private storage key. The application route is the
    # only link a frontend receives, and it performs its own permission check.
    return {
        "id": str(asset.pk),
        "kind": asset.kind,
        "purpose": asset.purpose,
        "position": asset.position,
        "is_cover": asset.is_cover,
        "processing_status": asset.processing_status,
        "url": reverse("asset_download", kwargs={"pk": asset.pk}),
    }


def machine_document(machine):
    """Serialize the current private record without rendering a template or starting work."""
    category = None
    if machine.category_id:
        category = {"id": machine.category_id, "name": machine.category.name, "slug": machine.category.slug}
    approved_version = None
    if machine.approved_version_id:
        approved_version = {
            "id": machine.approved_version_id,
            "number": machine.approved_version.number,
            "created_at": machine.approved_version.created_at.isoformat(),
        }
    return _json_value({
        "schema_version": "private-machine-v1",
        "id": str(machine.pk),
        "folio": machine.folio,
        "title": machine.title,
        "revision": machine.revision,
        "status": machine.status,
        "availability": machine.availability,
        "editable": machine.editable,
        "created_at": machine.created_at.isoformat(),
        "updated_at": machine.updated_at.isoformat(),
        "category": category,
        "approved_version": approved_version,
        "data": machine.data,
        "provenance": machine.provenance,
        "assets": [_asset_document(asset) for asset in machine.assets.all()],
    })


def machine_detail(request, pk):
    if request.method != "GET":
        response = _private_response({"error": "Método no permitido."}, status=405)
        response["Allow"] = "GET"
        return response
    if not _can_read_machine(request.user):
        return _private_response({"error": "Inicia sesión para continuar."}, status=401)
    try:
        machine = _machine_for_reader(request.user, pk)
    except Machine.DoesNotExist:
        return _private_response({"error": "El registro no está disponible."}, status=404)
    return _private_response(machine_document(machine))
