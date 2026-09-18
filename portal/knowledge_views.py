"""Private browsing views for the reviewed technical-reference library."""
import json
from urllib.parse import urlparse

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from .category_profiles import PROFILE_FIELD_LABELS, display_field_value
from .models import Category, TechnicalReference
from .research import LABELS as DISPLAY_LABELS
from .security import operator_required


def _selected_choice(value, choices):
    """Keep unknown query values from becoming implicit filters."""
    return value if value in {choice for choice, _label in choices} else ""


def _library_filters(request):
    query = request.GET.get("q", "").strip()[:100]
    status = _selected_choice(request.GET.get("status", ""), TechnicalReference.Review.choices)
    market = request.GET.get("market", "").strip()[:80]
    category = request.GET.get("category", "").strip()

    references = TechnicalReference.objects.select_related("category")
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

    return references, {"q": query, "status": status, "market": market, "category": category}


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
    page = Paginator(references, 20).get_page(request.GET.get("page"))
    return render(request, "portal/knowledge_library.html", {
        "references": page,
        "page_obj": page,
        "coverage": coverage,
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
    return render(request, "portal/knowledge_detail.html", {
        "reference": reference,
        "specifications": _display_specs(reference.specs),
        "source_href": _source_href(reference.source),
        "scope": _display_scope(provenance.get("scope")),
        "market_scope": reference.market or ("Global" if provenance.get("market_scope") == "global" else "No especificado"),
        "provenance_note": provenance.get("note", ""),
        "authority": provenance.get("authority", ""),
    })
