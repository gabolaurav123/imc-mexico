"""Semantic shape checks for literal web values; never infer or rewrite facts."""
import re
import unicodedata


# These are whole values, not keywords to find inside a promotional sentence.
# Electric/battery are retained because catalogues use the same fuel/power field.
_FUEL_NAMES = frozenset({
    "diesel", "diesel fuel", "combustible diesel", "gasoil", "gas oil", "gasoleo",
    "biodiesel", "bio diesel", "hvo", "hvo100", "ulsd", "diesel no. 2", "diesel #2",
    "gasolina", "gasoline", "petrol", "nafta", "gasolina sin plomo",
    "unleaded gasoline", "unleaded petrol", "gasolina premium", "gasolina regular",
    "gas", "gas natural", "natural gas", "gas natural comprimido", "compressed natural gas",
    "gas natural licuado", "liquefied natural gas", "gnc", "cng", "gnl", "lng",
    "glp", "lpg", "lp", "gas lp", "gas l.p", "gas l.p.", "gas licuado de petroleo",
    "liquefied petroleum gas", "autogas", "propano", "propane", "butano", "butane", "biogas",
    "hidrogeno", "hydrogen", "etanol", "ethanol", "metanol", "methanol",
    "queroseno", "kerosene", "keroseno",
    "electrico", "electrica", "electric", "electricidad", "electricity",
    "bateria", "baterias", "battery", "batteries", "battery electric", "electrico a bateria",
    "electrica a bateria", "electrico por bateria", "electrica por bateria",
})
_JOINER = re.compile(r"\s*(?:[/+,&-]|\b(?:y|and)\b)\s*")


def _literal_names(value):
    """A fuel name or up to three explicit components, including fuel aliases."""
    if value in _FUEL_NAMES:
        return True
    parts = _JOINER.split(value)
    return 2 <= len(parts) <= 3 and all(part in _FUEL_NAMES for part in parts)


def is_valid_research_field_value(key, value):
    """Veto invalid fuel prose; other fields retain their existing validation.

    A true result is only a shape check. The caller must still require a literal
    value in a retrieved citation and an exact compatible equipment identity.
    """
    if key != "fuel":
        return True
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        return False
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = " ".join(normalized.split()).translate(str.maketrans({"–": "-", "—": "-", "‑": "-"}))
    normalized = normalized.removesuffix(".").strip()
    if _literal_names(normalized):
        return True
    # Common table forms: Gas natural (GNC), or Híbrido (diésel / eléctrico).
    # Both sides are bounded noun lists; no free-form parenthetical prose.
    match = re.fullmatch(r"([^()]+)\s*\(([^()]+)\)", normalized)
    if match:
        main, detail = (part.strip() for part in match.groups())
        return (main in {"hibrido", "hibrida", "hybrid"} or _literal_names(main)) and _literal_names(detail)
    return False
