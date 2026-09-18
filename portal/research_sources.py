"""Verified public search starting points, not evidence or serial registries.

This module performs no requests and grants no authority to a field. A result
still needs matching identity, a cited passage, and the research validators.
The date records the manual verification described in docs/research-sources.md.
"""

from dataclasses import dataclass
import ipaddress
import re
import unicodedata
from typing import Literal
from urllib.parse import urlsplit


SourceKind = Literal['manufacturer', 'technical_catalog', 'public_documentation']
VERIFIED_ON = '2026-09-16'


@dataclass(frozen=True, slots=True)
class BrandProfile:
    brand: str
    aliases: tuple[str, ...]
    manufacturer_domains: tuple[str, ...]
    documentation_urls: tuple[str, ...]
    access_note: str
    source_kind: Literal['manufacturer'] = 'manufacturer'
    verified_on: str = VERIFIED_ON
    # Regional product catalogues can be verified for direct, model-scoped
    # reads without making their host a global web-search manufacturer domain.
    catalog_domains: tuple[str, ...] = ()
    catalog_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceProfile:
    name: str
    domains: tuple[str, ...]
    documentation_urls: tuple[str, ...]
    access_note: str
    source_kind: Literal['technical_catalog'] = 'technical_catalog'
    verified_on: str = VERIFIED_ON


MANUFACTURERS = (
    BrandProfile(
        brand='Caterpillar', aliases=('Cat',),
        manufacturer_domains=('cat.com',),
        documentation_urls=(
            'https://www.cat.com/en_US/support/maintenance/service-manuals.html',
        ),
        access_note='Página pública; algunos manuales requieren compra, SIS2GO o distribuidor.',
    ),
    BrandProfile(
        brand='Komatsu', aliases=(), manufacturer_domains=('komatsu.com',),
        documentation_urls=('https://www.komatsu.com/en-us/products/equipment/excavators',),
        access_note='Catálogo público y fichas por modelo; cobertura regional, no registro por serie.',
    ),
    BrandProfile(
        brand='Volvo Construction Equipment', aliases=('Volvo', 'Volvo CE'),
        manufacturer_domains=('volvoce.com',),
        documentation_urls=(
            'https://www.volvoce.com/global/en/products-and-services/past-products/',
        ),
        access_note='Archivo público de modelos anteriores; años de producción del modelo, no de una unidad.',
    ),
    BrandProfile(
        brand='John Deere', aliases=('Deere',), manufacturer_domains=('deere.com',),
        documentation_urls=(
            'https://www.deere.com/en-us/parts-owner-support/manuals-training',
            'https://rmi.techpubs.deere.com/Products/ProductSearch.aspx',
        ),
        access_note='Portal de manuales; extracción limitada en la página moderna y documentos con compra o suscripción.',
    ),
    BrandProfile(
        brand='JLG', aliases=('JLG Industries',), manufacturer_domains=('jlg.com',),
        documentation_urls=('https://www.jlg.com/en/support-and-services/troubleshooting',),
        access_note='Página pública con acceso a publicaciones; Online Express solicita cuenta gratuita.',
    ),
    BrandProfile(
        brand='Bobcat', aliases=('Bobcat Company',), manufacturer_domains=('bobcat.com',),
        documentation_urls=('https://www.bobcat.com/na/en/parts-service/service/manuals',),
        access_note='Página pública de manuales; el catálogo enlaza documentación ofrecida en tienda.',
    ),
    BrandProfile(
        brand='DEVELON', aliases=('Develon CE',), manufacturer_domains=('develon-ce.com',),
        documentation_urls=(
            'https://eu.develon-ce.com/en/products/crawler-excavators',
            'https://na.develon-ce.com/fr/construction-equipment/crawler-excavators/dx350lc-7',
        ),
        access_note='Sitios regionales oficiales de equipos DEVELON; las fichas de producto identifican modelos, no unidades fotografiadas.',
        verified_on='2026-09-18',
        catalog_domains=('develon-ce.cl',),
        catalog_urls=('https://develon-ce.cl/product-category/excavadoras-sobre-orugas/',),
    ),
)


TECHNICAL_CATALOGS = (
    SourceProfile(
        name='LECTURA Specs', domains=('lectura-specs.com',),
        documentation_urls=('https://www.lectura-specs.com/',),
        access_note='Catálogo externo público; datos de modelo y cobertura variable. API comercial no contratada ni integrada.',
    ),
    SourceProfile(
        name='RitchieSpecs', domains=('ritchiespecs.com',),
        documentation_urls=('https://www.ritchiespecs.com/',),
        access_note='Catálogo externo público; especificaciones de unidad base que pueden variar con opciones.',
    ),
)

# Material handling is a separate documentation family. This profile selects
# search entry points only; it does not infer the maker or origin of a unit.
CAT_LIFT_TRUCKS = BrandProfile(
    brand='Caterpillar', aliases=('Cat',),
    manufacturer_domains=('logisnextamericas.com', 'catlifttruck.com'),
    documentation_urls=(
        'https://www.logisnextamericas.com/en/logisnext/our-brands',
        'https://www.logisnextamericas.com/en/logisnext/support/service',
        'https://www.catlifttruck.com/catr-lift-trucks-story-success',
    ),
    access_note='Cat Lift Trucks: documentación de manutención, incluidos modelos históricos MCFA. La dirección de una empresa no acredita país de fabricación.',
)
FORKLIFT_CATALOGS = (
    SourceProfile(
        name='MachineTools', domains=('machinetools.com',),
        documentation_urls=('https://www.machinetools.com/',),
        access_note='Catálogo de maquinaria con modelos de montacargas históricos. Cobertura y unidades variables; sin lector directo cuando deniega acceso.',
    ),
    TECHNICAL_CATALOGS[0],
)


def catalogs_for_category(category=None):
    return FORKLIFT_CATALOGS if category == 'Montacargas' else TECHNICAL_CATALOGS


def _brand_key(name: str) -> str:
    # Whole aliases only: CAT is not a match for "CAT 320" or "Bobcat".
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', name).casefold()))


def lookup_brand(name: object, category=None) -> BrandProfile | None:
    """Return a verified brand profile for an exact normalized alias, or None.

    An unknown brand never borrows another manufacturer's domains. HESSEN is
    intentionally absent: no source was linked to the requested public models.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    key = _brand_key(name)
    if category == 'Montacargas' and key in {'cat', 'caterpillar'}:
        return CAT_LIFT_TRUCKS
    for profile in MANUFACTURERS:
        if key in {_brand_key(alias) for alias in (profile.brand, *profile.aliases)}:
            return profile
    return None


def _public_host(url: object) -> str | None:
    """Conservative URL parsing only; this is not a network/SSRF validator."""
    if not isinstance(url, str) or not url or any(char.isspace() or ord(char) < 32 for char in url):
        return None
    if '\\' in url:
        return None
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (parsed.scheme not in {'http', 'https'} or not host
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 80, 443}):
            return None
        host = host.rstrip('.').lower()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return None
        if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', host):
            return None
        if host.endswith(('.localhost', '.local', '.internal', '.invalid')):
            return None
        return host
    except (TypeError, ValueError):
        return None


def _matches_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith('.' + domain)


def source_kind(url: object, brand: object = None, category=None) -> SourceKind | None:
    """Classify a result's origin without verifying its claims or fetching it.

    With a brand, only that brand's verified domains count as manufacturer.
    Without a brand, any catalogued manufacturer domain may match. Unknown
    public origins return public_documentation, which means UNCLASSIFIED and
    does not assert a document was found. Invalid/non-public URLs return None.
    Redirect destinations must be classified again by the caller.
    """
    host = _public_host(url)
    if host is None:
        return None
    for catalog in (*TECHNICAL_CATALOGS, *FORKLIFT_CATALOGS):
        if any(_matches_domain(host, domain) for domain in catalog.domains):
            return 'technical_catalog'
    if brand is None:
        profiles = (*MANUFACTURERS, CAT_LIFT_TRUCKS)
    else:
        profile = lookup_brand(brand, category)
        profiles = (profile,) if profile else ()
    if any(_matches_domain(host, domain) for profile in profiles for domain in profile.manufacturer_domains):
        return 'manufacturer'
    return 'public_documentation'
