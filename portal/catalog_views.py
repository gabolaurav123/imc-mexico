"""Read-only catalogue of currently shareable approved machinery."""
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.core.paginator import Paginator
from django.db.models import F
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Category, MachineVersion, Publication
from .public_data import public_json
from .structured_data import _MAXIMUMS

UNDERCARRIAGE_LABELS = {"crawler": "Orugas", "wheeled": "Ruedas", "special": "Especial"}
CURRENCIES = ("MXN", "USD", "EUR")
AVAILABILITY_CHOICES = (
    ("available", "Disponibles"),
    ("reserved", "Reservadas"),
    ("sold", "Vendidas"),
    ("all", "Todas las publicadas"),
)
SORT_OPTIONS = (
    ("latest", "Más recientes"),
    ("hours_asc", "Horas: menor a mayor"),
    ("year_desc", "Año: más nuevo"),
    ("price_asc", "Precio: menor a mayor"),
    ("price_desc", "Precio: mayor a menor"),
)
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


def _year(value):
    """Return a supported whole catalogue year, or an explanatory error."""
    if not value:
        return None, None
    number = _decimal(value)
    if number is None or number != number.to_integral_value():
        return None, "El año debe ser un número entero."
    # Bound the Decimal before converting it to int. This keeps a query such
    # as ``1e999999999`` from requesting an enormous integer allocation.
    if not Decimal("1800") <= number <= Decimal("2200"):
        return None, "El año debe estar entre 1800 y 2200."
    return int(number), None


def _range_error(minimum, maximum, label, limit):
    """Validate an optional numeric range without treating an empty bound as zero."""
    lower = _decimal(minimum)
    upper = _decimal(maximum)
    if minimum and lower is None:
        return f"El mínimo de {label} debe ser un número válido."
    if maximum and upper is None:
        return f"El máximo de {label} debe ser un número válido."
    if lower is not None and lower < 0:
        return f"El mínimo de {label} no puede ser negativo."
    if upper is not None and upper < 0:
        return f"El máximo de {label} no puede ser negativo."
    # Compare Decimals before they reach a DecimalField lookup. A syntactically
    # valid exponent such as 1e999999999 would otherwise overflow its database
    # adapter while rendering a public URL.
    if lower is not None and lower >= limit:
        return f"El mínimo de {label} excede el límite permitido."
    if upper is not None and upper >= limit:
        return f"El máximo de {label} excede el límite permitido."
    if lower is not None and upper is not None and lower > upper:
        return f"El mínimo de {label} no puede superar el máximo."
    return None


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
        "hours_min", "hours_max", "year", "year_min", "year_max", "year_mode",
        "availability", "price_min", "price_max",
        "weight_min", "weight_max", "depth_min", "depth_max", "sort")}
    filter_warnings = []
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
        if currency in CURRENCIES:
            qs = qs.filter(version__currency=currency)
        else:
            qs = qs.none()
            filter_warnings.append("La moneda solicitada no es válida.")

    preservation = filters["preservation_condition"].casefold()
    if preservation:
        preservation = PRESERVATION_ALIASES.get(preservation, preservation)
        filters["preservation_condition"] = preservation
        qs = qs.filter(version__preservation_condition=preservation) if preservation in dict(PRESERVATION_CHOICES) else qs.none()

    availability = filters["availability"] or "available"
    if availability not in dict(AVAILABILITY_CHOICES):
        availability = "available"
        filter_warnings.append("La disponibilidad solicitada no es válida; se muestran disponibles.")
    filters["availability"] = availability
    if availability != "all":
        qs = qs.filter(machine__availability=availability)

    range_errors = [error for error in (
        _range_error(filters["hours_min"], filters["hours_max"], "horas", _MAXIMUMS["hours"]),
        _range_error(filters["price_min"], filters["price_max"], "precio", _MAXIMUMS["price"]),
        _range_error(filters["weight_min"], filters["weight_max"], "peso", _MAXIMUMS["weight_kg"]),
        _range_error(filters["depth_min"], filters["depth_max"], "profundidad", _MAXIMUMS["digging_depth_m"]),
    ) if error]
    if range_errors:
        qs = qs.none()
        filter_warnings.extend(range_errors)

    if not range_errors:
        for key, lookup in (("hours_min", "gte"), ("hours_max", "lte"),
                            ("price_min", "gte"), ("price_max", "lte"),
                            ("weight_min", "gte"), ("weight_max", "lte"),
                            ("depth_min", "gte"), ("depth_max", "lte")):
            field = {"weight": "weight_kg", "depth": "digging_depth_m"}.get(key.split("_")[0], key.split("_")[0])
            if hasattr(MachineVersion, field):
                qs = _filter_number(qs, f"version__{field}", filters.get(key), lookup)
    if (filters["price_min"] or filters["price_max"]) and not currency:
        qs = qs.none()
        filter_warnings.append("Para filtrar por precio, elige una moneda.")

    filters["year_mode"] = "approx" if filters["year_mode"] == "approx" else "exact"
    exact_year, year_error = _year(filters["year"])
    year_min, year_min_error = _year(filters["year_min"])
    year_max, year_max_error = _year(filters["year_max"])
    for error in (year_error, year_min_error, year_max_error):
        if error:
            filter_warnings.append(error)
    if year_error or year_min_error or year_max_error:
        qs = qs.none()
    elif year_min is not None and year_max is not None and year_min > year_max:
        qs = qs.none()
        filter_warnings.append("El año desde no puede ser posterior al año hasta.")
    elif filters["year_mode"] == "approx":
        # An approximate record matches when its declared period overlaps the
        # requested period. A one-sided range remains useful to browse open
        # ended periods without inventing an exact unit year.
        if year_min is not None:
            qs = qs.filter(version__estimated_year_to__gte=year_min)
        if year_max is not None:
            qs = qs.filter(version__estimated_year_from__lte=year_max)
    else:
        if year_min is not None:
            qs = qs.filter(version__year__gte=year_min)
        if year_max is not None:
            qs = qs.filter(version__year__lte=year_max)

    # Keep the established single-year query parameter working for existing
    # links. In approximate mode it asks whether the period contains that year.
    if exact_year is not None:
        if filters["year_mode"] == "approx":
            qs = qs.filter(version__estimated_year_from__lte=exact_year,
                           version__estimated_year_to__gte=exact_year)
        else:
            qs = qs.filter(version__year=exact_year)

    sort = filters["sort"] if filters["sort"] in dict(SORT_OPTIONS) else "latest"
    # Price ordering is meaningful only within one currency.  Fall back to the
    # stable recency order when no currency was selected, rather than mixing
    # incomparable amounts.
    if sort.startswith("price_") and not currency:
        sort = "latest"
        filter_warnings.append("Para ordenar por precio, elige una moneda.")
    ordering = {
        "latest": ["-updated_at", "pk"],
        "hours_asc": [F("version__hours").asc(nulls_last=True), "-updated_at", "pk"],
        "year_desc": [F("version__year").desc(nulls_last=True), "-updated_at", "pk"],
        "price_asc": [F("version__price").asc(nulls_last=True), "-updated_at", "pk"],
        "price_desc": [F("version__price").desc(nulls_last=True), "-updated_at", "pk"],
    }[sort]
    filters["sort"] = sort
    ordered_qs = qs.select_related("machine", "version", "version__category").order_by(*ordering)
    result_count = ordered_qs.count()
    page = Paginator(ordered_qs, 18).get_page(params.get("page"))
    query_params = params.copy()
    query_params.pop("page", None)
    query_params["sort"] = sort
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
                      "title": title, "year": version.year,
                      "availability": publication.machine.availability,
                      "availability_label": publication.machine.get_availability_display(),
                      "url": f"/ficha/{publication.token}/?back={quote(back, safe='')}"})
    return render(request, "portal/catalogue.html", {
        "cards": cards, "page_obj": page, "result_count": result_count, "query": query, "filters": filters,
        "categories": categories, "undercarriage_labels": UNDERCARRIAGE_LABELS.items(),
        "currencies": CURRENCIES, "preservation_choices": PRESERVATION_CHOICES,
        "availability_choices": AVAILABILITY_CHOICES, "filter_warnings": filter_warnings,
        "sort_options": SORT_OPTIONS,
    })
