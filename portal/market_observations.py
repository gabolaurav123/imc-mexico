"""Shared selection of dated market observations for research and administration."""
from datetime import date, datetime
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.utils import timezone


def market_unit_key(row):
    unit = " ".join(unicodedata.normalize("NFKC", row.unit_key or "").split()).casefold()
    if unit:
        return row.equipment_model_id, "unit", unit
    source = (row.source or "").strip()
    try:
        url = urlsplit(source)
        query = [(key, value) for key, value in parse_qsl(url.query, keep_blank_values=True)
                 if not key.lower().startswith("utm_") and key.lower() not in {"gclid", "fbclid"}]
        source = urlunsplit((url.scheme.lower(), url.netloc.lower(), url.path, urlencode(sorted(query)), ""))
    except ValueError:
        pass
    return row.equipment_model_id, "source", source


def latest_market_observations(queryset, *, today=None):
    """Deduplicate before filtering condition/age, so older offers cannot revive.

    Callers select their approved, active observations first. Future-dated or
    malformed observations are excluded, and ties prefer the latest inserted row.
    Tracking parameters do not make a second independent comparable.
    """
    today = today or timezone.localdate()
    seen, observations = set(), []
    for row in queryset.order_by("-retrieved_at", "-pk"):
        observed = row.retrieved_at
        if not isinstance(observed, date) or isinstance(observed, datetime) or observed > today:
            continue
        key = market_unit_key(row)
        if key in seen:
            continue
        seen.add(key)
        observations.append(row)
    return observations
