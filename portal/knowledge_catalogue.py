"""Install the reviewed release bundle in the existing relational database.

The manifest is an explicit release allowlist. Arbitrary JSON imports remain
pending; deploying does not activate them or overwrite an administrator's work.
"""
from datetime import date
import hashlib
import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from .models import Brand, Category, EquipmentModel, TechnicalReference


KNOWLEDGE_ROOT = Path(__file__).resolve().parent.parent / "knowledge"


def validate_record(item):
    if not isinstance(item, dict):
        raise CommandError("Cada referencia debe ser un objeto JSON.")
    required = ("category_slug", "brand", "model", "source", "source_title", "retrieved_at")
    for key in (*required, "variant", "generation", "market", "source_version"):
        value = item.get(key, "")
        if not isinstance(value, str) or (key in required and not value.strip()):
            raise CommandError(f"{key}: debe contener texto válido.")
    for key in ("specs", "provenance"):
        if not isinstance(item.get(key, {}), dict):
            raise CommandError(f"{key}: debe ser un objeto estructurado.")
    for key in ("period_from", "period_to"):
        if item.get(key) is not None and type(item[key]) is not int:
            raise CommandError(f"{key}: debe ser un año numérico o null.")


def bundled_records(root=None):
    root = Path(root or KNOWLEDGE_ROOT).resolve()
    try:
        manifest = json.loads((root / "bundled.json").read_text(encoding="utf-8"))
        records = []
        for entry in manifest["files"]:
            path = (root / entry["path"]).resolve()
            if not path.is_relative_to(root) or path.suffix != ".json":
                raise ValueError("La ruta de conocimiento queda fuera del paquete.")
            raw = path.read_bytes()
            if hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() != entry["sha256"]:
                raise ValueError(f"El contenido de {entry['path']} no coincide con la versión revisada.")
            items = json.loads(raw)["references"]
            if not isinstance(items, list):
                raise ValueError("Se esperaba una lista de referencias.")
            for item in items:
                validate_record(item)
            records.extend(items)
        return records
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise CommandError(f"No se pudo validar el paquete de conocimiento: {exc}") from exc


def link_catalogue(reference):
    """Link model documentation to suggestions without modifying existing rows."""
    brand = Brand.objects.filter(name__iexact=reference.brand).first()
    if brand is None:
        brand = Brand.objects.create(name=reference.brand)
    model = EquipmentModel.objects.filter(brand=brand, name__iexact=reference.model).first()
    if model is None:
        model = EquipmentModel.objects.create(brand=brand, name=reference.model, category=reference.category)
    # A staff reclassification must never be reversed by a seed or an import.
    if model.category_id == reference.category_id:
        reference.equipment_model = model
    return reference


@transaction.atomic
def install_bundled_knowledge(root=None):
    created = 0
    for item in bundled_records(root):
        try:
            category = Category.objects.get(slug=item["category_slug"])
            lookup = {"category": category, **{key: str(item.get(key, "")).strip()
                      for key in ("brand", "model", "variant", "generation", "market", "source")}}
            existing = TechnicalReference.objects.filter(**lookup).first()
            if existing:
                if existing.equipment_model_id is None:
                    link_catalogue(existing)
                    existing.full_clean()
                    existing.save(update_fields=["equipment_model", "updated_at"])
                continue
            reference = TechnicalReference(**lookup, **{key: item.get(key) for key in ("period_from", "period_to")},
                specs=item["specs"], provenance=item["provenance"], source_title=item["source_title"],
                source_version=item.get("source_version", ""), retrieved_at=date.fromisoformat(item["retrieved_at"]),
                review=TechnicalReference.Review.APPROVED, active=True, reviewed_at=timezone.now())
            link_catalogue(reference)
            reference.full_clean()
            reference.save()
            created += 1
        except (KeyError, TypeError, ValueError, Category.DoesNotExist, ValidationError) as exc:
            raise CommandError(f"Referencia de conocimiento inválida: {exc}") from exc
    return created
