"""Install the reviewed release bundle in the existing relational database.

The manifest is an explicit release allowlist. Arbitrary JSON imports remain
pending; deploying does not activate them or overwrite an administrator's work.
"""
from datetime import date
from collections import defaultdict
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
    aliases = item.get("provenance", {}).get("model_aliases")
    if aliases is not None:
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise CommandError("provenance.model_aliases: debe ser una lista de textos no vacíos.")
        from .research import identifier_key
        normalized = [identifier_key(alias) for alias in aliases]
        if len(normalized) != len(set(normalized)):
            raise CommandError("provenance.model_aliases: no debe repetir aliases equivalentes.")
    for key in ("period_from", "period_to"):
        if item.get(key) is not None and type(item[key]) is not int:
            raise CommandError(f"{key}: debe ser un año numérico o null.")
    retrieved_at = item["retrieved_at"]
    try:
        parsed_date = date.fromisoformat(retrieved_at)
    except ValueError as exc:
        raise CommandError("retrieved_at: debe usar AAAA-MM-DD.") from exc
    if parsed_date.isoformat() != retrieved_at:
        raise CommandError("retrieved_at: debe usar AAAA-MM-DD.")
    if parsed_date > timezone.localdate():
        raise CommandError("retrieved_at: la fecha de consulta no puede estar en el futuro.")


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
    """Link only one unambiguous catalogue model; never merge staff entries."""
    from .research import _brand_key, identifier_key

    brands = [brand for brand in Brand.objects.all()
              if _brand_key(brand.name) == _brand_key(reference.brand)]
    if not brands:
        brand = Brand.objects.create(name=reference.brand)
    elif len(brands) == 1:
        brand = brands[0]
    else:
        # Case or alias collisions require an explicit staff decision. Choosing
        # one could attach a source to the wrong product family.
        return reference

    models = [model for model in EquipmentModel.objects.filter(brand=brand)
              if identifier_key(model.name) == identifier_key(reference.model)]
    if not models:
        model = EquipmentModel.objects.create(brand=brand, name=reference.model, category=reference.category)
    elif len(models) == 1:
        model = models[0]
    else:
        return reference
    # A staff reclassification must never be reversed by a seed or an import.
    if model.category_id == reference.category_id:
        reference.equipment_model = model
    return reference


@transaction.atomic
def install_bundled_knowledge(root=None):
    """Validate and install in batches; an unchanged restart performs no writes.

    Keep the same category locks and never overwrite a reviewed staff record.
    In-memory indexes replace repeated scans of every brand/model for every row.
    """
    from .research import _brand_key, identifier_key
    records = bundled_records(root)
    keys = ("brand", "model", "variant", "generation", "market", "source")
    categories = {row.slug: row for row in Category.objects.select_for_update().filter(
        slug__in={item["category_slug"] for item in records}).order_by("pk")}
    if missing := {item["category_slug"] for item in records} - categories.keys():
        raise CommandError("Categorías desconocidas: " + ", ".join(sorted(missing)))
    brands = defaultdict(list)
    for row in Brand.objects.all():
        brands[_brand_key(row.name)].append(row)
    new_brands = []
    for item in records:
        key = _brand_key(item["brand"])
        if key not in brands:
            row = Brand(name=item["brand"].strip())
            row.full_clean(validate_unique=False, validate_constraints=False)
            brands[key].append(row)
            new_brands.append(row)
    Brand.objects.bulk_create(new_brands, batch_size=500)
    models = defaultdict(list)
    for row in EquipmentModel.objects.select_related("brand"):
        models[(row.brand_id, identifier_key(row.name))].append(row)
    new_models = []
    for item in records:
        candidates = brands[_brand_key(item["brand"])]
        if len(candidates) != 1:
            continue
        brand = candidates[0]
        key = (brand.pk, identifier_key(item["model"]))
        if key not in models:
            row = EquipmentModel(brand=brand, name=item["model"].strip(), category=categories[item["category_slug"]])
            row.full_clean(exclude=["brand", "category"], validate_unique=False, validate_constraints=False)
            models[key].append(row)
            new_models.append(row)
    EquipmentModel.objects.bulk_create(new_models, batch_size=500)
    existing = {}
    for row in TechnicalReference.objects.filter(category_id__in=[row.pk for row in categories.values()]).order_by("pk"):
        existing.setdefault((row.category_id, *(getattr(row, key) for key in keys)), row)
    pending, repairs = [], []
    try:
        for item in records:
            category = categories[item["category_slug"]]
            values = {key: str(item.get(key, "")).strip() for key in keys}
            key = (category.pk, *(values[name] for name in keys))
            row = existing.get(key)
            if row is not None and row.equipment_model_id is not None:
                continue
            is_new = row is None
            if is_new:
                row = TechnicalReference(category=category, **values,
                    **{name: item.get(name) for name in ("period_from", "period_to")},
                    specs=item["specs"], provenance=item["provenance"], source_title=item["source_title"].strip(),
                    source_version=item.get("source_version", "").strip(), retrieved_at=date.fromisoformat(item["retrieved_at"]),
                    review=TechnicalReference.Review.APPROVED, active=True, reviewed_at=timezone.now())
            candidates = brands[_brand_key(row.brand)]
            matches = models.get((candidates[0].pk, identifier_key(row.model)), []) if len(candidates) == 1 else []
            if len(matches) == 1 and matches[0].category_id == row.category_id:
                row.equipment_model = matches[0]
            # FK objects came from locked categories and the validated indexes.
            # Model.clean still checks identity, periods, approval and JSON types.
            row.full_clean(exclude=["category", "equipment_model", "reviewed_by"],
                           validate_unique=False, validate_constraints=False)
            if is_new:
                pending.append(row)
                existing[key] = row
            elif row.equipment_model_id is not None:
                row.updated_at = timezone.now()
                repairs.append(row)
        TechnicalReference.objects.bulk_create(pending, batch_size=250)
        if repairs:
            TechnicalReference.objects.bulk_update(repairs, ["equipment_model", "updated_at"], batch_size=250)
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise CommandError(f"Referencia de conocimiento inválida: {exc}") from exc
    return len(pending)
