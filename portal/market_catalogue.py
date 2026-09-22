"""Dated, reviewed market observations, separate from technical specifications."""
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from django.core.management.base import CommandError
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import EquipmentModel, MarketReference
from .research import _brand_aliases, identifier_key

ROOT = Path(__file__).resolve().parent.parent / 'knowledge' / 'market'
MAX_REFERENCE_AGE_DAYS = 30
COUNTRY_MARKETS = {'netherlands': 'NL', 'the netherlands': 'NL', 'mexico': 'MX', 'united states': 'US',
                   'usa': 'US', 'spain': 'ES', 'germany': 'DE', 'france': 'FR', 'italy': 'IT',
                   'canada': 'CA', 'united kingdom': 'GB', 'uk': 'GB'}


def _market(item):
    value = str(item.get('market') or '').strip().upper()
    if not value:
        value = COUNTRY_MARKETS.get(str(item.get('country') or '').strip().lower(), '')
    if not value:
        raise CommandError('El anuncio debe declarar un mercado ISO o país reconocible.')
    return value


@transaction.atomic
def install_bundled_market(root=None):
    """Release allowlist only; preserve staff edits and deactivations on reseed."""
    root = Path(root or ROOT).resolve()
    manifest = root / 'bundled.json'
    if not manifest.exists():
        return 0
    created = 0
    try:
        entries = json.loads(manifest.read_text(encoding='utf-8'))['files']
        if not isinstance(entries, list):
            raise TypeError('files no es una lista')
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CommandError('No se pudo leer el manifiesto de mercado revisado.') from exc
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str) or not isinstance(entry.get('sha256'), str):
            raise CommandError('El manifiesto de mercado contiene una entrada inválida.')
        path = (root / entry['path']).resolve()
        if not path.is_relative_to(root) or path.suffix != '.json':
            raise CommandError('Ruta de mercado fuera del paquete.')
        raw = path.read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise CommandError('La referencia de mercado no coincide con la versión revisada.')
        try:
            payload = json.loads(raw)
            subject = payload['subject']
            listings = payload['listings']
            if not isinstance(subject, dict) or not isinstance(listings, list):
                raise TypeError('estructura inválida')
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CommandError('El paquete de mercado no contiene un sujeto y anuncios válidos.') from exc
        try:
            model = EquipmentModel.objects.get(brand__name__iexact=subject['brand'],
                name__iexact=subject['model'], category__slug=subject['category_slug'])
        except (KeyError, TypeError, EquipmentModel.DoesNotExist, EquipmentModel.MultipleObjectsReturned) as exc:
            raise CommandError('El anuncio debe vincular una marca, modelo y categoría exactos del catálogo.') from exc
        for item in listings:
            if not isinstance(item, dict):
                raise CommandError('El anuncio de mercado no contiene campos válidos.')
            source = str(item.get('url') or '').strip()
            if not source:
                raise CommandError('El anuncio de mercado no contiene una URL válida.')
            if MarketReference.objects.filter(source=source).exists():
                continue
            try:
                observed_at = date.fromisoformat(item['observed_at'])
                if observed_at.isoformat() != item['observed_at']:
                    raise ValueError('fecha no canónica')
                if observed_at > timezone.localdate():
                    raise CommandError('La fecha observada del anuncio no puede estar en el futuro.')
                market = _market(item)
                price_type = item.get('price_type', 'asking')
                row = MarketReference(equipment_model=model, source=source,
                source_title=item.get('title') or f"{subject['brand']} {subject['model']} · {item['source']}",
                price=Decimal(str(item['price'])), currency=item['currency'], market=market,
                price_type=price_type, condition=item['condition'], year=item.get('year'),
                hours=item.get('hours'), retrieved_at=observed_at,
                evidence=item['evidence'], configurations=item.get('configurations', {}),
                unit_key=item.get('unit_key', ''), review='approved', active=True, reviewed_at=timezone.now())
                # ``source`` is unique and is checked again at save time so a
                # concurrent release import remains idempotent.
                row.full_clean(validate_unique=False)
            except (KeyError, TypeError, ValueError, ValidationError) as exc:
                raise CommandError('El anuncio de mercado no contiene campos válidos.') from exc
            try:
                with transaction.atomic():
                    row.save()
            except IntegrityError:
                if MarketReference.objects.filter(source=source).exists():
                    continue
                raise
            created += 1
    return created


def valuation_from_library(identity, category):
    """Use exact, active model references for 30 days; never infer an identity."""
    from .valuation import _configuration_key, range_from_comparables, _seal, _MARKET_NAMES
    from .market_observations import latest_market_observations, market_unit_key
    if not isinstance(identity, dict) or not category or not identity.get('brand') or not identity.get('model'):
        return None
    configurations = identity.get('configurations', {})
    compatibility_context = identity.get('compatibility', {})
    if not isinstance(configurations, dict) or not isinstance(compatibility_context, dict):
        return None
    brand_query = Q()
    for alias in _brand_aliases(identity['brand']):
        brand_query |= Q(equipment_model__brand__name__iexact=alias)
    today = timezone.localdate()
    oldest_allowed = today - timedelta(days=MAX_REFERENCE_AGE_DAYS)
    rows = MarketReference.objects.filter(brand_query, equipment_model__category=category,
        equipment_model__active=True, equipment_model__brand__active=True,
        review='approved', active=True).select_related('equipment_model__brand')
    comparable = []
    # Choose the latest observation for each unit before checking age, state or
    # compatibility. An older ad cannot reappear merely because its replacement
    # omitted a detail or changed its documented condition.
    for row in latest_market_observations(rows, today=today):
        if row.retrieved_at < oldest_allowed:
            continue
        if identifier_key(row.equipment_model.name) != identifier_key(identity['model']):
            continue
        if (row.market not in _MARKET_NAMES or row.currency not in {'USD', 'MXN', 'EUR'}
                or row.price_type not in {'asking', 'sold'}
                or row.condition not in {'new', 'used', 'refurbished', 'for_repair'}
                or not isinstance(row.configurations, dict) or not isinstance(row.evidence, str)):
            continue
        try:
            valid_price = row.price > 0
        except (TypeError, ValueError, ArithmeticError):
            valid_price = False
        if not valid_price:
            continue
        if identity.get('condition') and row.condition != identity['condition']:
            continue
        if any(_configuration_key(row.configurations.get(key)) != _configuration_key(value)
               for key, value in configurations.items()):
            continue
        # Reject documented incompatible variants/years, never guess a discount.
        compatibility = {**row.configurations, **({'year': str(row.year)} if row.year else {})}
        if any(key != 'hours' and key in compatibility and identifier_key(value) != identifier_key(compatibility[key])
               for key, value in compatibility_context.items()):
            continue
        unit = market_unit_key(row)
        comparable.append({'url': row.source, 'title': row.source_title, 'price': str(row.price),
            'currency': row.currency, 'market': row.market, 'price_type': row.price_type,
            'condition': row.condition, 'retrieved_at': row.retrieved_at.isoformat(),
            'brand': identity['brand'], 'model': identity['model'], 'evidence': row.evidence,
            'configurations': row.configurations, 'compatibility': compatibility,
            '_unit_hash': hashlib.sha256(str(unit[2]).encode()).hexdigest() if unit[1] == 'unit' else ''})
    value = range_from_comparables(comparable, identity)
    if value['status'] not in {'estimated', 'conditional_reference'}:
        return None
    value['diagnostics'] = {'parser': 'reviewed_market_library', 'accepted_comparable_count': len(comparable)}
    return _seal(value)
