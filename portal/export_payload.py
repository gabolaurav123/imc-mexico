"""Build the public, reproducible portion of an editorial export.

The export view is deliberately kept out of this module: it owns permissions,
PDF generation, and publication bookkeeping.  This module only turns an
*already approved* immutable version into JSON plus the exact asset bytes that
the JSON describes.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from uuid import UUID

from django.core.exceptions import ValidationError

from .public_data import public_json


# Export archives are assembled in memory by the current view.  Keep the helper
# bounded too, so an unexpectedly large video cannot make that behaviour worse.
MAX_EXPORT_ASSET_BYTES = 100 * 1024 * 1024
# The ZIP view currently holds every emitted asset in memory.  A total ceiling
# keeps a collection of individually valid videos from exhausting that host.
MAX_EXPORT_TOTAL_BYTES = 128 * 1024 * 1024

_PIL_MIMES = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "GIF": ("image/gif", ".gif"),
    "WEBP": ("image/webp", ".webp"),
    "TIFF": ("image/tiff", ".tiff"),
    "BMP": ("image/bmp", ".bmp"),
}


def _read_export_file(field, *, maximum=MAX_EXPORT_ASSET_BYTES):
    """Read a storage object with a fixed maximum, returning its exact bytes."""
    with field.open("rb") as stream:
        chunks = []
        total = 0
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > maximum:
                raise ValidationError("Un archivo autorizado excede el límite de exportación.")
            chunks.append(chunk)


def _content_description(raw, asset):
    """Identify the emitted file, rather than trusting the source file label."""
    if asset.kind == "image":
        try:
            from PIL import Image
            with Image.open(BytesIO(raw)) as image:
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                mime, suffix = _PIL_MIMES.get(image.format, ("application/octet-stream", ".bin"))
                if mime.startswith("image/"):
                    return mime, suffix, image.width, image.height
        except (ImportError, OSError, ValueError) as exc:
            raise ValidationError("Una imagen autorizada no es un archivo de imagen válido.") from exc
        raise ValidationError("Una imagen autorizada usa un formato no exportable.")
    # ISO Base Media (MP4/MOV) and WebM are the video formats the application
    # can process.  Unknown content is exported safely as an opaque binary.
    if len(raw) >= 12 and raw[4:8] == b"ftyp" and raw[8:12] == b"qt  ":
        return "video/quicktime", ".mov", None, None
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        return "video/mp4", ".mp4", None, None
    if raw.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm", ".webm", None, None
    return "application/octet-stream", ".bin", None, None


def _valid_asset_ids(raw_ids):
    if not isinstance(raw_ids, list):
        raise ValidationError("La lista de archivos públicos de la versión no es válida.")
    try:
        return [str(UUID(str(value))) for value in raw_ids]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationError("La versión contiene un identificador de archivo inválido.") from exc


def _approved_version_for(machine, version):
    if getattr(version, "machine_id", None) != getattr(machine, "pk", None):
        raise ValidationError("La versión no pertenece a esta maquinaria.")
    if getattr(machine, "approved_version_id", None) != getattr(version, "pk", None):
        raise ValidationError("La versión solicitada no es la versión aprobada actual.")


def validate_export_manifest(machine, version, payload):
    """Recheck media authorization after file preparation or before an ack."""
    _approved_version_for(machine, version)
    manifest = payload.get('assets', [])
    if not isinstance(manifest, list):
        raise ValidationError('El manifiesto de fotografías no es válido.')
    from uuid import UUID
    try:
        ids = [str(UUID(row['id'])) for row in manifest]
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValidationError('El manifiesto contiene un archivo no válido.') from exc
    if len(ids) != len(set(ids)):
        raise ValidationError('El manifiesto contiene archivos duplicados.')
    snapshot = version.data
    allowed = set(snapshot.get('public_asset_ids', []))
    from .services import detected_plate_asset_ids
    private = set(snapshot.get('private_plate_asset_ids', [])) | detected_plate_asset_ids(machine)
    if set(ids) - allowed or set(ids) & private:
        raise ValidationError('Una fotografía dejó de estar autorizada para esta versión.')
    current = {str(pk) for pk in machine.assets.filter(pk__in=ids, public_authorized=True,
        processing_status='ready', purpose__in=('general', 'detail')).values_list('pk', flat=True)}
    if current != set(ids):
        raise ValidationError('Una fotografía cambió de permisos durante la entrega.')


def build_export_payload(machine, version, *, include_private_metadata=False):
    """Return ``(payload, files)`` for the current approved version.

    ``files`` is a list of ``(archive_path, bytes)`` pairs.  The caller can
    write it to a ZIP without reopening a private storage path.  No source
    storage names are present in the payload.
    """
    _approved_version_for(machine, version)
    snapshot = version.data if isinstance(version.data, dict) else {}
    public_ids = _valid_asset_ids(snapshot.get("public_asset_ids", []))
    private_plate_ids = set(str(value) for value in (snapshot.get("private_plate_asset_ids", []) or []))
    # The historical snapshot is only one layer of protection.  A later image
    # analysis can classify a current asset as plate evidence, and it must stop
    # being exportable immediately just as it stops being public in a sheet.
    from .services import detected_plate_asset_ids
    private_plate_ids.update(detected_plate_asset_ids(machine))

    # The machine relation is intentional: a UUID in a historical snapshot is
    # never authority to export an asset belonging to a different machine.
    candidates = machine.assets.filter(
        pk__in=public_ids,
        processing_status="ready",
        public_authorized=True,
        purpose__in=("general", "detail"),
    ).exclude(pk__in=private_plate_ids)
    assets = sorted(candidates, key=lambda asset: (asset.position, str(asset.pk)))

    title = snapshot.get("title")
    exported = public_json(
        snapshot,
        title=title,
        category=snapshot.get("category_name"),
        availability=machine.availability,
    )
    exported.update({
        "folio": machine.folio,
        "machine_id": str(machine.pk),
        "version": version.number,
        "destination_status": "exported",
        "assets": [],
    })
    if include_private_metadata:
        # This is deliberately separate from public-machine-v1 data.  The
        # route authenticates server-side; the UUID is stable for operators.
        exported["metadata"] = {"private_return_url": f"/panel/maquinarias/{machine.pk}/"}

    files = []
    cover_assigned = False
    exported_bytes = 0
    for asset in assets:
        source = asset.preview if asset.preview else asset.original
        if not source:
            continue
        remaining = MAX_EXPORT_TOTAL_BYTES - exported_bytes
        if remaining <= 0:
            raise ValidationError("Los archivos autorizados exceden el límite total de exportación.")
        raw = _read_export_file(source, maximum=min(MAX_EXPORT_ASSET_BYTES, remaining))
        exported_bytes += len(raw)
        mime_type, suffix, width, height = _content_description(raw, asset)
        path = f"fotografias/{asset.pk}{suffix}"
        manifest = {
            "id": str(asset.pk),
            "path": path,
            "kind": asset.kind,
            "mime_type": mime_type,
            "size": len(raw),
            "sha256": sha256(raw).hexdigest(),
            "cover": bool(asset.is_cover and not cover_assigned),
            "position": asset.position,
        }
        if manifest["cover"]:
            cover_assigned = True
        if width is not None:
            manifest.update({"width": width, "height": height, "aspect_ratio": width / height})
        exported["assets"].append(manifest)
        files.append((path, raw))
    if not cover_assigned:
        first_image = next((item for item in exported["assets"] if item["kind"] == "image"), None)
        if first_image:
            first_image["cover"] = True
    return exported, files
