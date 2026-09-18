"""Read-only catalogue of currently shareable approved machinery."""
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.core.paginator import Paginator
from django.db.models import F
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Category, MachineVersion, Publication
from .public_data import public_json

UNDERCARRIAGE_LABELS = {"crawler": "Orugas", "wheeled": "Ruedas", "special": "Especial"}
CURRENCIES = ("MXN", "USD", "EUR")
PRESERVATION_CHOICES = (("excellent", "Excelente"), ("good", "Buena"),
                        ("acceptable", "Aceptable"), ("poor", "Deficiente"))
PRESERVATION_ALIASES = {"excelente": "excellent", "buena": "good", "bueno": "good",
                        "aceptable": "acceptable", "deficiente": "poor", "poor": "poor"}


def _decimal(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _filter_number(queryset, field, value, lookup="gte"):
    number = _decimal(value)
    if number is None:
        return queryset
    return queryset.filter(**{f"{field}__{lookup}": number})


def _public_publications():
    return Publication.objects.filter(destination="share", enabled=True, status="published",
                                      machine__deleted_at__isnull=True,
                                      machine__availability__in=["available", "reserved", "sold"],
                                      machine__owner__advertiser_status="approved",
                                      version_id__isnull=False,
                                      version__approved_machines__isnull=False,
                                      version_id=F("machine__approved_version_id"))


@require_GET
def catalogue(request):
    """Public search over the approved snapshot's immutable typed projection."""
    params = request.GET
    public_qs = _public_publications()
    category_ids = public_qs.filter(version__category__active=True).values_list(
        "version__category_id", flat=True).distinct()
    categories = Category.objects.filter(active=True, pk__in=category_ids).order_by("name")
    filters = {key: params.get(key, "").strip() for key in (
        "category", "brand", "model", "variant", "undercarriage", "currency",
        "location_country", "location_region", "location_city", "preservation_condition",
        "hours_min", "hours_max", "year", "year_mode", "price_min", "price_max",
        "weight_min", "weight_max", "depth_min", "depth_max")}
    qs = public_qs

    category = filters["category"]
    selected_category = None
    if category:
        selected_category = (categories.filter(pk=category).first() if category.isdigit()
                             else categories.filter(slug=category).first())
        if selected_category is None:
            qs = qs.none()
        else:
            filters["category"] = str(selected_category.pk)
            qs = qs.filter(version__category=selected_category)

    for key in ("brand", "model", "variant", "location_country", "location_region", "location_city"):
        if filters[key]:
            qs = qs.filter(**{f"version__{key}__iexact": filters[key]})
    if filters["undercarriage"]:
        qs = qs.filter(version__undercarriage=filters["undercarriage"])

    currency = filters["currency"].upper()
    if currency:
        filters["currency"] = currency
        qs = qs.filter(version__currency=currency) if currency in CURRENCIES else qs.none()

    preservation = filters["preservation_condition"].casefold()
    if preservation:
        preservation = PRESERVATION_ALIASES.get(preservation, preservation)
        filters["preservation_condition"] = preservation
        qs = qs.filter(version__preservation_condition=preservation) if preservation in dict(PRESERVATION_CHOICES) else qs.none()

    for key, lookup in (("hours_min", "gte"), ("hours_max", "lte"), ("year_min", "gte"),
                        ("year_max", "lte"), ("price_min", "gte"), ("price_max", "lte"),
                        ("weight_min", "gte"), ("weight_max", "lte"),
                        ("depth_min", "gte"), ("depth_max", "lte")):
        field = {"weight": "weight_kg", "depth": "digging_depth_m"}.get(key.split("_")[0], key.split("_")[0])
        if hasattr(MachineVersion, field):
            qs = _filter_number(qs, f"version__{field}", filters.get(key), lookup)
    if (filters["price_min"] or filters["price_max"]) and not currency:
        qs = qs.none()

    filters["year_mode"] = "approx" if filters["year_mode"] == "approx" else "exact"
    exact_year = _decimal(filters["year"])
    if exact_year is not None:
        if filters["year_mode"] == "approx":
            qs = qs.filter(version__estimated_year_from__lte=exact_year,
                           version__estimated_year_to__gte=exact_year)
        else:
            qs = qs.filter(version__year=exact_year)

    page = Paginator(qs.select_related("machine", "version", "version__category").order_by("-updated_at"), 18).get_page(params.get("page"))
    query_params = params.copy()
    query_params.pop("page", None)
    query = query_params.urlencode()
    cards = []
    for publication in page:
        version = publication.version
        published = public_json(version.data)
        data = published["data"]
        title_parts = [str(data.get(key, "")).strip() for key in ("brand", "model", "variant")]
        title = " ".join(part for part in title_parts if part) or published.get("title") or "Maquinaria disponible"
        assets = version.data.get("public_asset_ids", [])
        undercarriage_label = UNDERCARRIAGE_LABELS.get(data.get("undercarriage"), data.get("undercarriage", ""))
        summary = data.get("hours") is not None and f"{data['hours']} horas" or ""
        if undercarriage_label:
            summary = f"{summary} · {undercarriage_label}" if summary else undercarriage_label
        back = "/maquinaria/" + (f"?{query}" if query else "")
        cards.append({"publication": publication, "data": data, "asset_ids": assets[:1], "summary": summary,
                      "title": title, "url": f"/ficha/{publication.token}/?back={quote(back, safe='')}"})
    return render(request, "portal/catalogue.html", {
        "cards": cards, "page_obj": page, "query": query, "filters": filters,
        "categories": categories, "undercarriage_labels": UNDERCARRIAGE_LABELS.items(),
        "currencies": CURRENCIES, "preservation_choices": PRESERVATION_CHOICES,
    })
