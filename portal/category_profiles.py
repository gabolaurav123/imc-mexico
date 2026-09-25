"""Category-specific vocabulary used by intake, research and presentation.

Profiles are declarative on purpose.  They do not alter a ``Category`` row and
therefore cannot accidentally turn an existing non-excavator category into an
excavator.  ``Category.fields`` remains the database-owned list of editable
legacy fields; a profile only adds an opt-in vocabulary for its own slug.
"""
from __future__ import annotations

from copy import deepcopy
import unicodedata


EXCAVATOR_FIELDS = (
    "variant", "machine_family", "undercarriage", "boom_configuration",
    "stick_configuration", "size_class", "application", "hours",
    "hours_basis", "hours_recorded_at", "year", "estimated_year_from",
    "estimated_year_to", "weight", "digging_depth", "power", "capacity",
    "location_country", "location_region", "location_city", "condition",
    "preservation_condition", "price", "currency", "power_type",
    "depth_configuration",
)


def _options(*values):
    return [{"value": value, "label": label} for value, label in values]


EXCAVATOR_PROFILE = {
    "key": "excavator",
    "label": "Excavadora",
    "aliases": ["excavadora", "excavadoras", "excavadora hidraulica", "excavadora hidráulica", "excavator"],
    "classification": {
        "machine_family": _options(
            ("hydraulic_excavator", "Excavadora hidráulica"),
            ("other_excavation_system", "Otro sistema de excavación"),
        ),
        "undercarriage": _options(
            ("crawler", "Orugas"), ("wheeled", "Ruedas"),
            ("special", "Equipo especial"),
        ),
        "boom_configuration": _options(
            ("standard", "Pluma estándar"), ("two_piece", "Pluma de dos piezas"),
            ("straight", "Pluma recta"), ("demolition_high_reach", "Frente de demolición de gran alcance"),
            ("long_reach", "Pluma de largo alcance"), ("articulated", "Configuración articulada"),
            ("other", "Otra configuración documentada"),
        ),
        "stick_configuration": _options(
            ("standard", "Brazo o balancín estándar"), ("short", "Brazo corto"),
            ("long", "Brazo largo"), ("telescopic", "Brazo telescópico"),
            ("other", "Otra configuración documentada"),
        ),
        "size_class": _options(
            ("mini", "Mini"), ("small", "Pequeña"), ("medium", "Mediana"),
            ("large", "Grande"), ("mining", "Minería"),
        ),
        "application": _options(
            ("general_excavation", "Excavación general"), ("long_reach", "Largo alcance"),
            ("demolition", "Demolición"), ("material_handling", "Manipulación de materiales"),
            ("forestry", "Forestal"), ("other", "Otra aplicación"),
        ),
    },
    "fields": [
        {"key": "variant", "label": "Variante", "kind": "text", "optional": True},
        {"key": "machine_family", "label": "Familia de máquina", "kind": "choice", "optional": True},
        {"key": "undercarriage", "label": "Sistema de desplazamiento", "kind": "choice", "optional": True,
         "help": "Orugas y ruedas son configuraciones distintas."},
        {"key": "boom_configuration", "label": "Configuración de pluma", "kind": "choice", "optional": True},
        {"key": "stick_configuration", "label": "Configuración de brazo o balancín", "kind": "choice", "optional": True},
        {"key": "size_class", "label": "Clase de tamaño", "kind": "choice", "optional": True},
        {"key": "application", "label": "Aplicación", "kind": "choice", "optional": True},
        {"key": "hours_basis", "label": "Base de horas", "kind": "choice", "optional": True,
         "options": _options(("hourmeter", "Lectura de horómetro"), ("owner_declared", "Declaradas por el propietario"), ("documented", "Respaldadas por documentación"))},
    ],
    "photo_guidance": [
        "Máquina completa y ambos laterales", "Equipo de trabajo: pluma, brazo y cucharón",
        "Orugas o ruedas", "Cabina y horómetro", "Desgaste, daños y accesorios visibles",
        "Placa de identificación, si la tienes",
    ],
    "ai_instructions": "Identifica sólo una excavadora hidráulica cuando la evidencia lo sostenga. Distingue pluma de brazo o balancín; no conviertas una aplicación en una configuración ni confirmes especificaciones de catálogo para una unidad.",
    "sources": [
        {"name": "Caterpillar excavators", "url": "https://www.cat.com/en_GB/products/new/equipment/excavators.html", "kind": "manufacturer"},
        {"name": "Komatsu excavators", "url": "https://www.komatsu.com/en-us/products/equipment/excavators", "kind": "manufacturer"},
    ],
    "valuation_rules": {"requires_compatible_comparables": True, "minimum_independent_references": 2},
}

COMPACTOR_PROFILE = {
    "key": "compactor",
    "label": "Compactador",
    "aliases": ["compactador", "compactadores", "compactadora", "compactadoras", "rodillo compactador", "placa vibratoria"],
    "classification": {
        "machine_family": _options(
            ("vibratory_plate", "Placa vibratoria"), ("tandem_roller", "Rodillo tándem"),
            ("single_drum_roller", "Rodillo de un tambor"), ("rammer", "Apisonador"),
            ("other", "Otro compactador documentado"),
        ),
    },
    "fields": [
        {"key": "variant", "label": "Variante", "kind": "text", "optional": True},
        {"key": "machine_family", "label": "Familia de máquina", "kind": "choice", "optional": True},
        {"key": "working_width", "label": "Ancho de trabajo", "kind": "text", "optional": True},
        {"key": "maximum_weight", "label": "Peso operativo máximo", "kind": "text", "optional": True},
        {"key": "drum_type", "label": "Tipo de tambor", "kind": "text", "optional": True},
        {"key": "emissions", "label": "Etapa de emisiones", "kind": "text", "optional": True},
        {"key": "engine", "label": "Motor", "kind": "text", "optional": True},
        {"key": "drum_width", "label": "Ancho de tambor", "kind": "text", "optional": True},
        {"key": "drum_diameter", "label": "Diámetro de tambor", "kind": "text", "optional": True},
        {"key": "centrifugal_force", "label": "Fuerza centrífuga", "kind": "text", "optional": True},
        {"key": "vibration_frequency", "label": "Frecuencia de vibración", "kind": "text", "optional": True},
    ],
    "photo_guidance": [
        "Máquina completa y ambos laterales", "Placa de identificación y rótulo de modelo",
        "Placa base o tambores", "Horómetro y mandos", "Desgaste, daños y accesorios visibles",
    ],
    "ai_instructions": "Identifica el tipo de compactador sólo con evidencia. No confundas ancho de placa, tambor o transporte; conserva la variante de emisiones y tipo de tambor sólo si están documentados.",
    "sources": [
        {"name": "BOMAG", "url": "https://www.bomag.com/", "kind": "manufacturer"},
        {"name": "Wacker Neuson", "url": "https://www.wackerneuson.com/", "kind": "manufacturer"},
        {"name": "HAMM", "url": "https://www.hamm.eu/", "kind": "manufacturer"},
        {"name": "Dynapac", "url": "https://www.dynapac.com/", "kind": "manufacturer"},
    ],
    "valuation_rules": {"requires_compatible_comparables": True, "minimum_independent_references": 2},
}

PLATFORM_PROFILE = {
    "key": "aerial_platform", "label": "Plataforma elevadora",
    "aliases": ["plataforma elevadora", "plataforma de elevacion", "plataforma de elevación", "aerial lift", "boom lift", "scissor lift"],
    "classification": {"machine_family": _options(("articulating_boom", "Brazo articulado"),
                                                     ("telescopic_boom", "Brazo telescópico"),
                                                     ("crawler_boom", "Brazo sobre orugas"),
                                                     ("towable_boom", "Brazo remolcable"),
                                                     ("scissor", "Tijera"), ("other", "Otra plataforma documentada"))},
    "fields": [{"key": "machine_family", "label": "Familia de plataforma", "kind": "choice", "optional": True},
               {"key": "platform_height", "label": "Altura máxima de plataforma", "kind": "text", "optional": True},
               {"key": "horizontal_outreach", "label": "Alcance horizontal", "kind": "text", "optional": True},
               {"key": "capacity", "label": "Capacidad de plataforma", "kind": "text", "optional": True},
               {"key": "gradeability", "label": "Pendiente superable", "kind": "text", "optional": True},
               {"key": "swing", "label": "Giro", "kind": "text", "optional": True}],
    "ai_instructions": "No confundir alcance, altura de plataforma y capacidad. Una plataforma eléctrica, remolcable o sobre orugas es una familia distinta.",
    "sources": [{"name": "JLG", "url": "https://www.jlg.com/", "kind": "manufacturer"}],
    "valuation_rules": {"requires_compatible_comparables": True, "minimum_independent_references": 2},
}

LOADER_PROFILE = {
    "key": "compact_loader", "label": "Minicargador",
    "aliases": ["minicargador", "minicargadores", "skid steer", "skid-steer", "compact track loader", "cargador compacto"],
    "classification": {"undercarriage": _options(("wheeled", "Ruedas"), ("crawler", "Orugas"))},
    "fields": [{"key": "undercarriage", "label": "Sistema de desplazamiento", "kind": "choice", "optional": True},
               {"key": "power", "label": "Potencia", "kind": "text", "optional": True},
               {"key": "capacity", "label": "Capacidad operativa nominal", "kind": "text", "optional": True},
               {"key": "weight", "label": "Peso operativo", "kind": "text", "optional": True}],
    "ai_instructions": "Conserva el criterio de capacidad publicado, por ejemplo 35% de carga de vuelco; no lo equipares con carga de vuelco ni con un accesorio.",
    "sources": [{"name": "Caterpillar compact loaders", "url": "https://www.cat.com/", "kind": "manufacturer"}],
    "valuation_rules": {"requires_compatible_comparables": True, "minimum_independent_references": 2},
}

FORKLIFT_PROFILE = {
    "key": "forklift", "label": "Montacargas",
    "aliases": ["montacargas", "forklift", "fork lift", "carretilla elevadora", "lift truck"],
    "classification": {"power_type": _options(("electric", "Eléctrico"), ("lpg", "Gas LP"),
                                                     ("gasoline", "Gasolina"), ("diesel", "Diésel"),
                                                     ("other", "Otra energía documentada"))},
    "fields": [{"key": "power_type", "label": "Tipo de potencia", "kind": "choice", "optional": True},
               {"key": "capacity", "label": "Capacidad nominal", "kind": "text", "optional": True},
               {"key": "load_center", "label": "Centro de carga", "kind": "text", "optional": True},
               {"key": "lift_height", "label": "Altura de elevación", "kind": "text", "optional": True},
               {"key": "weight", "label": "Peso operativo", "kind": "text", "optional": True}],
    "ai_instructions": "No infieras capacidad por la altura de elevación. Conserva centro de carga y tipo de potencia publicados para comparar unidades compatibles.",
    "sources": [{"name": "Toyota Material Handling", "url": "https://www.toyotaforklift.com/", "kind": "manufacturer"}],
    "valuation_rules": {"requires_compatible_comparables": True, "minimum_independent_references": 2},
}

MOTOR_GRADER_PROFILE = {
    "key": "motor_grader", "label": "Motoconformadora",
    "aliases": ["motoconformadora", "motoniveladora", "motoniveladoras", "motor grader"],
    "classification": {},
    "fields": [{"key": "blade_width", "label": "Ancho de hoja", "kind": "text", "optional": True},
               {"key": "power", "label": "Potencia", "kind": "text", "optional": True},
               {"key": "weight", "label": "Peso operativo", "kind": "text", "optional": True}],
    "ai_instructions": "Conserva la variante de emisiones y el criterio de peso publicado; no deduzcas hoja, ripper u opciones por la apariencia.",
    "sources": [{"name": "Caterpillar motor graders", "url": "https://www.cat.com/", "kind": "manufacturer"}],
    "valuation_rules": {"requires_compatible_comparables": True, "minimum_independent_references": 2},
}

PROFILES = {"excavadoras": EXCAVATOR_PROFILE, "compactadores": COMPACTOR_PROFILE,
            "plataformas-elevadoras": PLATFORM_PROFILE, "minicargadores": LOADER_PROFILE,
            "montacargas": FORKLIFT_PROFILE, "motoniveladoras": MOTOR_GRADER_PROFILE}

PROFILE_FIELD_LABELS = {item["key"]: item["label"] for profile in PROFILES.values() for item in profile["fields"]}
PROFILE_FIELD_LABELS.update(power_type="Tipo de potencia", depth_configuration="Configuración de profundidad")


def display_field_value(key, value):
    """Translate controlled values for sheets without changing stored codes."""
    options = next((profile["classification"].get(key, []) for profile in PROFILES.values() if key in profile["classification"]), [])
    if not options:
        options = next((item.get("options", []) for profile in PROFILES.values() for item in profile["fields"] if item["key"] == key), [])
    if key == "power_type":
        options = _options(("net", "Potencia neta"), ("gross", "Potencia bruta"),
                           ("rated", "Potencia nominal"), ("other", "Otra"))
    return next((item["label"] for item in options if item["value"] == value), value)


def normalized_alias(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(char for char in text if not unicodedata.combining(char)).casefold().split())


def profile_for_category(category):
    """Return a detached profile dictionary, or an empty generic profile."""
    slug = getattr(category, "slug", category if isinstance(category, str) else "")
    profile = PROFILES.get(str(slug or "").casefold())
    return deepcopy(profile) if profile else {}


def category_catalog(categories):
    """Serialize active Category objects for local typeahead; never queries the web."""
    records = []
    for category in categories:
        if not getattr(category, "active", False):
            continue
        profile = profile_for_category(category)
        aliases = [category.name, category.slug, *profile.get("aliases", [])]
        records.append({"id": category.pk, "name": category.name, "slug": category.slug,
                        "aliases": list(dict.fromkeys(aliases)),
                        "fields": list(category.fields or []), "profile": profile})
    return records
