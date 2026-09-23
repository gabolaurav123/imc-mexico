"""Local preparation and acknowledgement of main-site transfers.

This module intentionally has no HTTP client.  A receipt is a reviewed record of
an external action, not evidence that this process contacted the main site.
"""
import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import IntegrationDelivery, Machine, Publication


def canonical_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError("La carga de integración debe ser JSON válido.") from exc


def payload_sha256(payload):
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def delivery_metadata(delivery):
    """Small stable envelope for exports and operator UIs; contains no credential."""
    return {
        "delivery_id": str(delivery.pk),
        "idempotency_key": str(delivery.pk),
        "payload_sha256": delivery.payload_sha256,
        "source_machine_id": str(delivery.source_machine_id),
        "version_id": delivery.version_id,
        "state": delivery.state,
    }


@transaction.atomic
def mark_delivery_exported(delivery, actor):
    """Advance only the local handoff state, rechecking after file preparation."""
    _require_publisher(actor)
    candidate = IntegrationDelivery.objects.select_related("publication").get(pk=delivery.pk)
    machine = Machine.objects.select_for_update(of=("self",)).select_related('owner').get(pk=candidate.source_machine_id)
    publication = Publication.objects.select_for_update().get(pk=candidate.publication_id)
    delivery = IntegrationDelivery.objects.select_for_update().get(pk=candidate.pk)
    if (publication.current_delivery_id != delivery.pk or machine.approved_version_id != delivery.version_id or not machine.owner.is_active
            or machine.owner.advertiser_status != 'approved' or machine.availability == 'withdrawn'
            or machine.deleted_at is not None or machine.availability != delivery.payload.get('availability')):
        raise ValidationError('La aprobación, autorización o disponibilidad cambió durante la exportación.')
    from .export_payload import validate_export_manifest
    validate_export_manifest(machine, delivery.version, delivery.payload)
    if not (publication.status == 'published' and publication.version_id == delivery.version_id):
        publication.status = 'exported'
    publication.version_id = delivery.version_id
    publication.enabled = False
    publication.save(update_fields=['version', 'status', 'enabled', 'updated_at'])
    return publication


def _require_publisher(actor):
    from .services import require_operator
    require_operator(actor, "portal.publish_machine")


@transaction.atomic
def prepare_delivery(machine, actor, payload):
    """Persist one idempotent, immutable-version handoff candidate without networking."""
    _require_publisher(actor)
    if not isinstance(payload, dict):
        raise ValidationError("La carga de integración debe ser un objeto JSON.")
    machine = Machine.objects.select_for_update(of=("self",)).select_related("owner", "approved_version").get(pk=machine.pk)
    if (not machine.approved_version_id or not machine.owner.is_active or machine.owner.advertiser_status != "approved"
            or machine.availability == "withdrawn"):
        raise ValidationError("Sólo puede prepararse una versión aprobada, autorizada y no retirada.")
    if (payload.get("machine_id") != str(machine.pk) or payload.get("version") != machine.approved_version.number
            or payload.get("availability") != machine.availability):
        raise ValidationError("La carga debe conservar la maquinaria y el número exacto de la versión aprobada.")
    from .export_payload import validate_export_manifest
    validate_export_manifest(machine, machine.approved_version, payload)
    digest = payload_sha256(payload)
    publication, _ = Publication.objects.select_for_update().get_or_create(
        machine=machine, destination="main", defaults={"version": machine.approved_version, "status": "approved"})
    changed_version = publication.version_id != machine.approved_version_id
    if changed_version:
        publication.version = machine.approved_version
        publication.status = "exported" if publication.status == "published" else "approved"
        publication.integration_state = "pending"
        publication.save(update_fields=["version", "status", "integration_state", "updated_at"])
    delivery, created = IntegrationDelivery.objects.get_or_create(
        publication=publication, version=machine.approved_version, payload_sha256=digest,
        defaults={"source_machine_id": machine.pk, "payload": json.loads(canonical_json(payload))})
    if not created and (delivery.source_machine_id != machine.pk or canonical_json(delivery.payload) != canonical_json(payload)):
        raise ValidationError("La entrega existente no coincide con su carga inmutable.")
    if publication.current_delivery_id != delivery.pk:
        publication.current_delivery = delivery
        publication.integration_state = "pending"
        publication.save(update_fields=["current_delivery", "integration_state", "updated_at"])
    if created:
        from .services import audit
        audit(actor, "integration.delivery_prepared", delivery, {"payload_sha256": digest, "version": delivery.version_id})
    return delivery


def _receipt_value(receipt, name, *, max_length=None):
    value = receipt.get(name)
    if not isinstance(value, str):
        raise ValidationError({name: "Debe ser texto."})
    if not value or value != value.strip() or any(ord(char) < 32 for char in value) or (max_length and len(value) > max_length):
        raise ValidationError({name: "Debe contener un valor válido."})
    return value


def _main_url(value):
    from urllib.parse import urlsplit
    if not value:
        return ""
    if not isinstance(value, str) or len(value) > 200 or value != value.strip() or any(ord(char) < 32 for char in value):
        raise ValidationError({"remote_url": "El enlace no es válido."})
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise ValidationError({"remote_url": "El enlace no es válido."}) from exc
    if (parsed.scheme != "https" or parsed.username or parsed.password or port not in {None, 443}
            or host not in {"imcmexico.com.mx", "www.imcmexico.com.mx"}):
        raise ValidationError({"remote_url": "El enlace publicado debe usar HTTPS de imcmexico.com.mx."})
    return value


@transaction.atomic
def ack_delivery(delivery, actor, receipt, evidence):
    """Record a manually checked remote receipt after proving it binds this delivery."""
    _require_publisher(actor)
    if not isinstance(receipt, dict):
        raise ValidationError("El acuse debe ser un objeto JSON.")
    candidate = IntegrationDelivery.objects.select_related("publication").get(pk=delivery.pk)
    # Keep the same lock order as preparation: Machine, Publication, Delivery.
    machine = Machine.objects.select_for_update(of=("self",)).select_related("approved_version", "owner").get(pk=candidate.publication.machine_id)
    publication = Publication.objects.select_for_update().get(pk=candidate.publication_id)
    delivery = IntegrationDelivery.objects.select_for_update().select_related("version").get(pk=candidate.pk)
    if (publication.current_delivery_id != delivery.pk or machine.approved_version_id != delivery.version_id or delivery.source_machine_id != machine.pk
            or delivery.version.machine_id != machine.pk or machine.deleted_at is not None
            or not machine.owner.is_active or machine.owner.advertiser_status != "approved"
            or machine.availability == "withdrawn" or delivery.payload.get("availability") != machine.availability):
        raise ValidationError("El acuse corresponde a una versión obsoleta o ajena.")
    if str(receipt.get("delivery_id", "")) != str(delivery.pk):
        raise ValidationError("El acuse no corresponde a esta entrega.")
    if receipt.get("payload_sha256") != delivery.payload_sha256:
        raise ValidationError("La huella del acuse no corresponde a la carga preparada.")
    if str(receipt.get("source_machine_id", "")) != str(machine.pk) or receipt.get("version_id") != delivery.version_id:
        raise ValidationError("La correlación de maquinaria o versión no coincide.")
    from .export_payload import validate_export_manifest
    validate_export_manifest(machine, delivery.version, delivery.payload)
    remote_id = _receipt_value(receipt, "remote_id", max_length=200)
    remote_reference = receipt.get("external_reference", "")
    if (not isinstance(remote_reference, str) or len(remote_reference) > 200
            or remote_reference != remote_reference.strip() or any(ord(char) < 32 for char in remote_reference)):
        raise ValidationError({"external_reference": "La referencia visible es demasiado larga."})
    status = str(receipt.get("status", "acknowledged")).strip().casefold()
    if status not in {"acknowledged", "published"}:
        raise ValidationError({"status": "El estado del acuse no es válido."})
    remote_url = _main_url(receipt.get("remote_url", ""))
    if status == "published" and not remote_url:
        raise ValidationError({"remote_url": "Una publicación confirmada requiere enlace HTTPS."})
    if not isinstance(evidence, str) or len(evidence.strip()) < 12 or len(evidence.strip()) > 4000:
        raise ValidationError({"evidence": "Registra evidencia independiente de 12 a 4 000 caracteres."})
    evidence = evidence.strip()
    if evidence in {remote_id, remote_reference, remote_url}:
        raise ValidationError({"evidence": "La evidencia debe ser independiente del identificador o enlace."})
    normalized_receipt = json.loads(canonical_json(receipt))
    # ``state`` is local display metadata, not remote evidence; it changes when
    # a delivery is acknowledged and must not defeat an otherwise identical retry.
    normalized_receipt.pop("state", None)
    if delivery.state == IntegrationDelivery.State.ACKNOWLEDGED:
        if canonical_json(delivery.receipt) != canonical_json(normalized_receipt) or delivery.evidence != evidence:
            raise ValidationError("La entrega ya tiene un acuse distinto.")
        if IntegrationDelivery.objects.filter(publication=publication, state=IntegrationDelivery.State.ACKNOWLEDGED,
                                              acknowledged_at__gt=delivery.acknowledged_at).exists():
            raise ValidationError("Existe un acuse posterior; registra una nueva entrega antes de reutilizar este comprobante.")
        stored_remote_id = delivery.receipt.get("remote_id", "")
        stored_reference = delivery.receipt.get("external_reference", "")
        stored_url = delivery.receipt.get("remote_url", "")
        if (publication.external_id != stored_remote_id or publication.external_reference != stored_reference
                or publication.external_url != stored_url):
            raise ValidationError("La publicación actual no coincide con este acuse histórico.")
        if publication.integration_state != "acknowledged":
            publication.integration_state = "acknowledged"
            publication.acknowledged_by = delivery.acknowledged_by
            publication.acknowledged_at = delivery.acknowledged_at
            publication.save(update_fields=["integration_state", "acknowledged_by", "acknowledged_at", "updated_at"])
        return delivery
    if publication.external_id and publication.external_id != remote_id:
        raise ValidationError("La publicación ya está vinculada a otro identificador remoto.")
    duplicate = Publication.objects.filter(destination="main", external_id=remote_id).exclude(pk=publication.pk).exists()
    if duplicate:
        raise ValidationError("El identificador remoto ya pertenece a otra publicación.")
    delivery.state = IntegrationDelivery.State.ACKNOWLEDGED
    delivery.receipt = normalized_receipt
    delivery.evidence = evidence
    delivery.acknowledged_by = actor
    delivery.acknowledged_at = timezone.now()
    delivery.full_clean()
    delivery.save(update_fields=["state", "receipt", "evidence", "acknowledged_by", "acknowledged_at"])
    publication.external_id = remote_id
    publication.external_reference = remote_reference
    publication.external_url = remote_url
    publication.integration_state = "acknowledged"
    publication.acknowledged_by = actor
    publication.acknowledged_at = delivery.acknowledged_at
    if status == "published":
        publication.status = "published"
    publication.full_clean()
    try:
        with transaction.atomic():
            publication.save()
    except IntegrityError as exc:
        raise ValidationError("El identificador remoto ya pertenece a otra publicación.") from exc
    from .services import audit
    audit(actor, "integration.delivery_acknowledged", delivery,
          {"remote_id": remote_id, "published": status == "published", "version": delivery.version_id})
    return delivery
