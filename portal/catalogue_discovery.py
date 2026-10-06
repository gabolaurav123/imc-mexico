"""Small, read-only catalogue discovery responses for the intake picker.

The old catalogue endpoint predates the large reference library and returns a
flat list of every selectable model.  This module deliberately walks the
identity hierarchy instead: category, then brand, then a bounded model page.
It exposes only reviewed model-level coverage; it never exposes a machine,
owner, source URL, or guest-session capability.
"""
from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.db.models import Count, Exists, F, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce, Lower, Replace
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .catalogue_intake import approved_catalogue_models
from .category_profiles import profile_for_category
from .models import Brand, Category, EquipmentModel, MarketReference, TechnicalReference
from .research import _brand_aliases, identifier_key


PAGE_SIZE = 25
MAX_PAGE = 10000
MAX_QUERY_LENGTH = 80
STAGES = frozenset({"categories", "brands", "models"})


def _positive_id(params, name, *, required=False):
    raw = params.get(name)
    if raw in (None, ""):
        if required:
            raise ValidationError(f"Selecciona un {name} disponible.")
        return None
    if not isinstance(raw, str) or len(raw) > 18 or not re.fullmatch(r"[1-9][0-9]*", raw):
        raise ValidationError(f"El identificador de {name} no es válido.")
    return int(raw)


def _page(params):
    raw = params.get("page", "1")
    if not isinstance(raw, str) or len(raw) > len(str(MAX_PAGE)) or not re.fullmatch(r"[1-9][0-9]*", raw):
        raise ValidationError("La página no es válida.")
    value = int(raw)
    if value > MAX_PAGE:
        raise ValidationError("La página solicitada está fuera del límite disponible.")
    return value


def _query(params):
    raw = params.get("q", "")
    if not isinstance(raw, str):
        raise ValidationError("La búsqueda no es válida.")
    value = " ".join(raw.split())
    if len(value) > MAX_QUERY_LENGTH:
        raise ValidationError("La búsqueda es demasiado larga.")
    return value


def _reference_filter(*filters, **extra):
    return TechnicalReference.objects.filter(
        equipment_model_id=OuterRef("pk"), category_id=OuterRef("category_id"),
        active=True, review=TechnicalReference.Review.APPROVED, *filters, **extra,
    )


def _model_queryset(*, category_id=None, brand_id=None, query=""):
    """Return selectable models with coverage summaries in one model query."""
    reference_counts = (TechnicalReference.objects.filter(
        equipment_model_id=OuterRef("pk"), category_id=OuterRef("category_id"),
        active=True, review=TechnicalReference.Review.APPROVED,
    ).order_by().values("equipment_model_id").annotate(total=Count("pk")).values("total"))
    queryset = (approved_catalogue_models()
        .annotate(
            reference_count=Coalesce(Subquery(reference_counts, output_field=IntegerField()), Value(0)),
            has_specs=Exists(_reference_filter(~Q(specs={}))),
            has_period=Exists(_reference_filter(period_from__isnull=False)),
            has_market=Exists(MarketReference.objects.filter(
                equipment_model_id=OuterRef("pk"), active=True,
                review=MarketReference.Review.APPROVED,
            )),
        ))
    if category_id is not None:
        queryset = queryset.filter(category_id=category_id)
    if brand_id is not None:
        queryset = queryset.filter(brand_id=brand_id)
    if query:
        # Search formatting differences such as "E 450 AJ" / "E450AJ" in
        # SQL.  A documented alternate spelling is also considered through
        # the reviewed reference provenance, never through unreviewed input.
        normalized = Lower(Replace(Replace(Replace(Replace(
            F("name"), Value(" "), Value("")), Value("-"), Value("")),
            Value("."), Value("")), Value("_"), Value("")))
        key = identifier_key(query)
        queryset = queryset.annotate(_search_name=normalized)
        # Keep the JSON lookup strictly inside the documented aliases.  A
        # generic provenance ``icontains`` can match an editor note or another
        # metadata value, which both produces surprising suggestions and makes
        # the database inspect a much larger JSON document for every model.
        # The raw spelling is intentional here: canonical model-name matching
        # above handles punctuation-insensitive searches, while this branch is
        # only for an explicitly documented alternate name.
        matching_alias = _reference_filter(provenance__model_aliases__icontains=query)
        queryset = queryset.annotate(_matching_alias=Exists(matching_alias)).filter(
            Q(_search_name__contains=key) | Q(_matching_alias=True))
    # At scale alphabetical first pages can contain old identity-only records
    # while a documented technical fiche is buried later.  Coverage is already
    # computed for the response, so it is a cheap and deterministic priority;
    # it is not presented as popularity or a ranking claim.
    return queryset.order_by("-has_specs", "-has_period", "-has_market", Lower("name"), "pk")


def _coverage_rows(category_id=None, brand_id=None):
    """Reference rows restricted to their model's exact category identity."""
    rows = TechnicalReference.objects.filter(
        active=True, review=TechnicalReference.Review.APPROVED,
        equipment_model__active=True, equipment_model__brand__active=True,
        equipment_model__category__active=True,
        equipment_model__category_id=F("category_id"),
    )
    if category_id is not None:
        rows = rows.filter(category_id=category_id)
    if brand_id is not None:
        rows = rows.filter(equipment_model__brand_id=brand_id)
    return rows


def _matches(value, query, aliases=()):
    if not query:
        return True
    needle = identifier_key(query)
    return any(needle in identifier_key(candidate) for candidate in (value, *aliases))


def _paginate(items, page):
    total = items.count() if hasattr(items, "count") else len(items)
    start = (page - 1) * PAGE_SIZE
    return list(items[start:start + PAGE_SIZE]), total


def _categories(query, page):
    rows = _coverage_rows().values("category_id").annotate(
        reference_count=Count("pk"), model_count=Count("equipment_model_id", distinct=True),
        has_specs=Count("pk", filter=~Q(specs={})),
    )
    # Category aliases live in the static category profile, not as a separate
    # user-editable alias table.  The number of categories stays small, so this
    # one bounded query preserves accent-insensitive aliases portably on both
    # SQLite and PostgreSQL.
    summaries = {row["category_id"]: row for row in rows}
    categories = Category.objects.filter(active=True, pk__in=summaries).order_by(Lower("name"), "pk")
    records = []
    for category in categories:
        aliases = profile_for_category(category).get("aliases", [])
        if not _matches(category.name, query, aliases):
            continue
        summary = summaries[category.pk]
        records.append({"id": category.pk, "label": category.name, "category_id": category.pk,
                        "category_name": category.name, "model_count": summary["model_count"],
                        "reference_count": summary["reference_count"],
                        "has_technical_reference": True, "has_specs": bool(summary["has_specs"]),
                        "can_prepare_from_catalogue": bool(summary["model_count"])})
    start = (page - 1) * PAGE_SIZE
    return records[start:start + PAGE_SIZE], len(records)


def _brands(category_id, query, page):
    rows = _coverage_rows(category_id=category_id).values("equipment_model__brand_id", "equipment_model__brand__name").annotate(
        reference_count=Count("pk"), model_count=Count("equipment_model_id", distinct=True),
        has_specs=Count("pk", filter=~Q(specs={})),
    ).order_by(Lower("equipment_model__brand__name"), "equipment_model__brand_id")
    records = []
    category = Category.objects.filter(pk=category_id, active=True).only("pk", "name").first()
    if not category:
        return records, 0
    if not query:
        # The regular cascade does not need alias expansion.  Keep its common
        # path in SQL so a large future category never materializes every
        # brand merely to return one small page.
        total = rows.count()
        start = (page - 1) * PAGE_SIZE
        page_rows = rows[start:start + PAGE_SIZE]
        return [{"id": row["equipment_model__brand_id"], "label": row["equipment_model__brand__name"],
                 "brand_id": row["equipment_model__brand_id"], "brand_name": row["equipment_model__brand__name"],
                 "category_id": category.pk, "category_name": category.name,
                 "model_count": row["model_count"], "reference_count": row["reference_count"],
                 "has_technical_reference": True, "has_specs": bool(row["has_specs"]),
                 "can_prepare_from_catalogue": bool(row["model_count"])} for row in page_rows], total
    for row in rows:
        name = row["equipment_model__brand__name"]
        if not _matches(name, query, _brand_aliases(name)):
            continue
        brand_id = row["equipment_model__brand_id"]
        records.append({"id": brand_id, "label": name, "brand_id": brand_id, "brand_name": name,
                        "category_id": category.pk, "category_name": category.name,
                        "model_count": row["model_count"], "reference_count": row["reference_count"],
                        "has_technical_reference": True, "has_specs": bool(row["has_specs"]),
                        "can_prepare_from_catalogue": bool(row["model_count"])})
    start = (page - 1) * PAGE_SIZE
    return records[start:start + PAGE_SIZE], len(records)


def _models(category_id, brand_id, query, page):
    category = Category.objects.filter(pk=category_id, active=True).only("pk", "name").first()
    brand = Brand.objects.filter(pk=brand_id, active=True).only("pk", "name").first()
    if not category or not brand:
        return [], 0
    rows, total = _paginate(_model_queryset(category_id=category_id, brand_id=brand_id, query=query), page)
    return [{"id": row.pk, "label": row.name, "model_id": row.pk, "model_name": row.name,
             "brand_id": brand.pk, "brand_name": brand.name,
             "category_id": category.pk, "category_name": category.name,
             "reference_count": row.reference_count, "has_technical_reference": True,
             "has_specs": row.has_specs, "has_period": row.has_period, "has_market": row.has_market,
             "can_prepare_from_catalogue": True} for row in rows], total


def discover(params):
    """Validate an intake discovery request and return its small response."""
    stage = params.get("stage", "categories")
    if stage not in STAGES:
        raise ValidationError("La etapa del catálogo no es válida.")
    page, query = _page(params), _query(params)
    category_id = _positive_id(params, "category", required=stage in {"brands", "models"})
    brand_id = _positive_id(params, "brand", required=stage == "models")
    if stage == "categories":
        items, total = _categories(query, page)
    elif stage == "brands":
        items, total = _brands(category_id, query, page)
    else:
        items, total = _models(category_id, brand_id, query, page)
    return {"stage": stage, "items": items, "page": page, "page_size": PAGE_SIZE,
            "total": total, "has_more": page < MAX_PAGE and page * PAGE_SIZE < total}


@require_GET
def api_catalogue_discovery(request):
    """Public reviewed catalogue metadata; safe for guest and signed-in intake."""
    try:
        return JsonResponse(discover(request.GET))
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
