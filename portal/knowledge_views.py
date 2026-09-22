"""Private browsing views for the reviewed technical-reference library."""
import json
from collections import defaultdict
from statistics import median
from urllib.parse import urlparse

from django.core.paginator import Paginator
from datetime import timedelta

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from .category_profiles import PROFILE_FIELD_LABELS, display_field_value
from .models import Category, MarketReference, TechnicalReference
from .market_catalogue import MAX_REFERENCE_AGE_DAYS
from .market_observations import latest_market_observations
from .valuation import configuration_signature
from .research import LABELS as DISPLAY_LABELS
from .security import operator_required


def _selected_choice(value, choices):
    """Keep unknown query values from becoming implicit filters."""
    return value if value in {choice for choice, _label in choices} else ""


def _library_filters(request):
    query = request.GET.get("q", "").strip()[:100]
    status = _selected_choice(request.GET.get("status", ""), TechnicalReference.Review.choices)
    market = request.GET.get("market", "").strip()[:80]
    category = request.GET.get("category", "").strip()[:20]
    if not category.isdigit() or len(category) > 18:
        category = ""
    availability = _selected_choice(request.GET.get("availability", ""), AVAILABILITY_CHOICES)

    today = timezone.localdate()
    current_market = MarketReference.objects.filter(equipment_model_id=OuterRef("equipment_model_id"),
        review=MarketReference.Review.APPROVED, active=True, price__gt=0,
        retrieved_at__range=(today - timedelta(days=MAX_REFERENCE_AGE_DAYS), today))
    references = TechnicalReference.objects.select_related("category").annotate(has_current_market=Exists(current_market))
    if query:
        references = references.filter(
            Q(category__name__icontains=query)
            | Q(brand__icontains=query)
            | Q(model__icontains=query)
            | Q(variant__icontains=query)
            | Q(generation__icontains=query)
        )
    if status:
        references = references.filter(review=status)
    if market:
        references = references.filter(market=market)
    if category.isdigit():
        references = references.filter(category_id=category)
    period = Q(period_from__isnull=False) | Q(period_to__isnull=False)
    if availability == "with_period":
        references = references.filter(period)
    elif availability == "without_period":
        references = references.exclude(period)
    elif availability == "with_market":
        references = references.filter(has_current_market=True)
    elif availability == "without_market":
        references = references.filter(has_current_market=False)

    return references, {"q": query, "status": status, "market": market, "category": category, "availability": availability}


AVAILABILITY_CHOICES = (
    ("with_period", "Con periodo documentado"), ("without_period", "Sin periodo documentado"),
    ("with_market", "Con anuncios vigentes"), ("without_market", "Sin anuncios vigentes"),
)


def _market_overview(model_ids):
    """Share the worker's newest-unit selection; never mix market or condition."""
    if not model_ids:
        return {}
    today = timezone.localdate()
    cutoff = today - timedelta(days=MAX_REFERENCE_AGE_DAYS)
    queryset = MarketReference.objects.filter(equipment_model_id__in=model_ids,
        review=MarketReference.Review.APPROVED, active=True)
    result = defaultdict(lambda: {"ranges": [], "listings": [], "historical": []})
    groups = defaultdict(list)
    for row in latest_market_observations(queryset, today=today):
        row.source_href = _source_href(row.source)
        overview = result[row.equipment_model_id]
        if row.retrieved_at < cutoff:
            overview["historical"].append(row)
            continue
        overview["listings"].append(row)
        if (row.price > 0 and row.condition in {"new", "used", "refurbished", "for_repair"}
                and row.price_type in {"asking", "sold"} and row.currency in {"USD", "MXN", "EUR"}
                and isinstance(row.configurations, dict) and isinstance(row.evidence, str)
                and row.evidence.strip() and row.source_href):
            groups[(row.equipment_model_id, row.market, row.currency, row.price_type, row.condition,
                    configuration_signature(row.configurations))].append(row)
    for (model_id, market, currency, price_type, condition, _configuration), rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        prices = [row.price for row in rows]
        result[model_id]["ranges"].append({
            "market": market, "currency": currency, "price_type": price_type, "condition": condition,
            "price_type_label": dict(MarketReference.PriceType.choices).get(price_type, price_type),
            "condition_label": dict(MarketReference.Condition.choices).get(condition, condition),
            "configuration": ", ".join(f"{_display_label(key)}: {value}" for key, value in rows[0].configurations.items()),
            "count": len(rows), "minimum": min(prices), "maximum": max(prices), "median": median(prices),
            "oldest": min(row.retrieved_at for row in rows), "newest": max(row.retrieved_at for row in rows),
        })
    return result


def _source_href(value):
    """Return only a complete HTTP(S) URL suitable for a staff-facing href."""
    if not isinstance(value, str) or len(value) > 1000:
        return ""
    try:
        parsed = urlparse(value.strip())
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        valid = False
    if not valid:
        return ""
    return value.strip()


def _display_label(key):
    return PROFILE_FIELD_LABELS.get(key) or DISPLAY_LABELS.get(key) or key.replace("_", " ").capitalize()


def _display_specs(specs):
    """Render structured values as readable model specifications, retaining evidence."""
    if not isinstance(specs, dict):
        return []
    rows = []
    for key, item in specs.items():
        value = item.get("value") if isinstance(item, dict) and "value" in item else item
        if value in (None, ""):
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        rows.append({
            "label": _display_label(key),
            "value": display_field_value(key, value),
            "evidence": item.get("evidence", "") if isinstance(item, dict) else "",
        })
    return rows


def _display_scope(value):
    return {"model": "Modelo", "family": "Familia de modelos", "variant": "Variante"}.get(value, value or "Modelo")


@require_GET
@operator_required("portal.view_technicalreference")
def technical_library(request):
    """List only staff-visible references; public routes never expose these records."""
    references, filters = _library_filters(request)
    coverage = {
        "references": references.count(),
        "categories": references.values("category_id").distinct().count(),
        "brands": references.values("brand").distinct().count(),
        "models": references.values("brand", "model").distinct().count(),
    }
    completeness = {
        "periods": references.filter(Q(period_from__isnull=False) | Q(period_to__isnull=False)).values("brand", "model").distinct().count(),
        "market_models": references.filter(has_current_market=True).values("brand", "model").distinct().count(),
    }
    page = Paginator(references, 20).get_page(request.GET.get("page"))
    overview = _market_overview({ref.equipment_model_id for ref in page if ref.equipment_model_id})
    for reference in page:
        reference.specification_count = len(_display_specs(reference.specs))
        reference.market_overview = overview.get(reference.equipment_model_id, {})
    return render(request, "portal/knowledge_library.html", {
        "references": page,
        "page_obj": page,
        "coverage": coverage,
        "completeness": completeness,
        "availability_choices": AVAILABILITY_CHOICES,
        "market_reference_age_days": MAX_REFERENCE_AGE_DAYS,
        "categories": Category.objects.filter(technical_references__isnull=False).distinct().order_by("name"),
        "markets": TechnicalReference.objects.exclude(market="").order_by("market").values_list("market", flat=True).distinct(),
        "review_choices": TechnicalReference.Review.choices,
        **filters,
    })


@require_GET
@operator_required("portal.view_technicalreference")
def technical_reference_detail(request, pk):
    reference = get_object_or_404(TechnicalReference.objects.select_related("category"), pk=pk)
    provenance = reference.provenance if isinstance(reference.provenance, dict) else {}
    overview = _market_overview([reference.equipment_model_id]).get(reference.equipment_model_id, {}) if reference.equipment_model_id else {}
    siblings = TechnicalReference.objects.filter(equipment_model_id=reference.equipment_model_id,
        category_id=reference.category_id, review=TechnicalReference.Review.APPROVED, active=True).exclude(pk=pk) if reference.equipment_model_id else []
    related = [{"reference": item, "specifications": _display_specs(item.specs), "source_href": _source_href(item.source)}
               for item in siblings]
    return render(request, "portal/knowledge_detail.html", {
        "reference": reference,
        "specifications": _display_specs(reference.specs),
        "source_href": _source_href(reference.source),
        "scope": _display_scope(provenance.get("scope")),
        "market_scope": reference.market or ("Global" if provenance.get("market_scope") == "global" else "No especificado"),
        "provenance_note": provenance.get("note", ""),
        "authority": provenance.get("authority", ""),
        "market_ranges": overview.get("ranges", []),
        "market_listings": overview.get("listings", []),
        "historical_market_listings": overview.get("historical", []),
        "related_references": related,
        "market_reference_age_days": MAX_REFERENCE_AGE_DAYS,
    })
