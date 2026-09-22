"""Dated, reviewed market observations, separate from technical specifications."""
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from django.core.management.base import CommandError
from django.core.exceptions import ValidationError
from django.db import transaction
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
    for entry in json.loads(manifest.read_text(encoding='utf-8'))['files']:
        path = (root / entry['path']).resolve()
        if not path.is_relative_to(root) or path.suffix != '.json':
            raise CommandError('Ruta de mercado fuera del paquete.')
        raw = path.read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise CommandError('La referencia de mercado no coincide con la versión revisada.')
        payload = json.loads(raw)
        try:
            subject = payload['subject']
            model = EquipmentModel.objects.get(brand__name__iexact=subject['brand'],
                name__iexact=subject['model'], category__slug=subject['category_slug'])
        except (KeyError, EquipmentModel.DoesNotExist, EquipmentModel.MultipleObjectsReturned) as exc:
            raise CommandError('El anuncio debe vincular una marca, modelo y categoría exactos del catálogo.') from exc
        for item in payload['listings']:
            if MarketReference.objects.filter(source=item['url']).exists():
                continue
            try:
                observed_at = date.fromisoformat(item['observed_at'])
                if observed_at > timezone.localdate():
                    raise CommandError('La fecha observada del anuncio no puede estar en el futuro.')
                market = _market(item)
                price_type = item.get('price_type', 'asking')
                row = MarketReference(equipment_model=model, source=item['url'],
                source_title=item.get('title') or f"{subject['brand']} {subject['model']} · {item['source']}",
                price=Decimal(str(item['price'])), currency=item['currency'], market=market,
                price_type=price_type, condition=item['condition'], year=item.get('year'),
                hours=item.get('hours'), retrieved_at=observed_at,
                evidence=item['evidence'], configurations=item.get('configurations', {}),
                unit_key=item.get('unit_key', ''), review='approved', active=True, reviewed_at=timezone.now())
                row.full_clean()
            except (KeyError, ValueError, ValidationError) as exc:
                raise CommandError('El anuncio de mercado no contiene campos válidos.') from exc
            row.save()
            created += 1
    return created


def valuation_from_library(identity, category):
    """Use exact, active model references for 30 days; never infer an identity."""
    from .valuation import _configuration_key, range_from_comparables, _seal, _MARKET_NAMES
    if not category or not identity.get('brand') or not identity.get('model'):
        return None
    brand_query = Q()
    for alias in _brand_aliases(identity['brand']):
        brand_query |= Q(equipment_model__brand__name__iexact=alias)
    today = timezone.localdate()
    rows = MarketReference.objects.filter(brand_query, equipment_model__category=category,
        equipment_model__active=True, equipment_model__brand__active=True,
        review='approved', active=True, retrieved_at__range=(today - timedelta(days=MAX_REFERENCE_AGE_DAYS), today)
        ).select_related('equipment_model__brand').order_by('-retrieved_at', 'pk')
    comparable, seen = [], set()
    for row in rows:
        if identifier_key(row.equipment_model.name) != identifier_key(identity['model']):
            continue
        if row.market not in _MARKET_NAMES or row.condition not in {'new', 'used', 'refurbished', 'for_repair'} or row.price <= 0:
            continue
        if identity.get('condition') and row.condition != identity['condition']:
            continue
        if any(_configuration_key(row.configurations.get(key)) != _configuration_key(value)
               for key, value in identity.get('configurations', {}).items()):
            continue
        # Reject documented incompatible variants/years, never guess a discount.
        compatibility = {**row.configurations, **({'year': str(row.year)} if row.year else {})}
        if any(key != 'hours' and key in compatibility and identifier_key(value) != identifier_key(compatibility[key])
               for key, value in identity.get('compatibility', {}).items()):
            continue
        unit = row.unit_key or row.source
        if unit in seen:
            continue
        seen.add(unit)
        comparable.append({'url': row.source, 'title': row.source_title, 'price': str(row.price),
            'currency': row.currency, 'market': row.market, 'price_type': row.price_type,
            'condition': row.condition, 'retrieved_at': row.retrieved_at.isoformat(),
            'brand': identity['brand'], 'model': identity['model'], 'evidence': row.evidence,
            'configurations': row.configurations, 'compatibility': compatibility,
            '_unit_hash': hashlib.sha256(row.unit_key.encode()).hexdigest() if row.unit_key else ''})
    value = range_from_comparables(comparable, identity)
    if value['status'] not in {'estimated', 'conditional_reference'}:
        return None
    value['diagnostics'] = {'parser': 'reviewed_market_library', 'accepted_comparable_count': len(comparable)}
    return _seal(value)
