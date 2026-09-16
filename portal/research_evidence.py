"""Small, deterministic checks for already cited evidence; no network or storage.

These checks do not establish a model match or an exact serial match. The caller
must still validate the citation, value, brand/model, and denied serial matches.
Country names remain literal: recognizing a label never translates its value.
"""
import re


_ORIGIN_LABEL = re.compile(
    r"\b(?:made\s+in|manufactured\s+in|fabricad[oa]\s+en|hech[oa]\s+en|"
    r"pa[ií]s\s+de\s+(?:fabricaci[oó]n|origen)|country\s+of\s+(?:manufacture|origin)|"
    r"hergestellt\s+in|gefertigt\s+in|herstellungsland|"
    r"fabriqu[eé]e?\s+(?:en|au|aux)|pays\s+de\s+fabrication|"
    r"fabbricat[oa]\s+in|prodott[oa]\s+in|paese\s+di\s+fabbricazione|"
    r"fabricad[oa]\s+(?:em|no|na)|pa[ií]s\s+de\s+(?:fabrica[cç][aã]o|origem))\b",
    re.I,
)
_DENIED_OR_UNCERTAIN = re.compile(
    r"\b(?:not|never|no|sin|nunca|desconocid[oa]|unknown|unconfirmed|uncertain|"
    r"nicht|kein\w*|unbekannt|ungekl[aä]rt|pas|non|sans|inconnu\w*|"
    r"n[aã]o|sem|sconosciut[oa]|"
    r"may|might|could|possibly|perhaps|allegedly|maybe|"
    r"posiblemente|probablemente|quiz[aá]s?|podr[ií]a|supuestamente|"
    r"k[oö]nnte|m[oö]glicherweise|peut[- ]?[eê]tre|pourrait|"
    r"forse|potrebbe|talvez|poderia|example|ejemplo|beispiel|exemple)\b",
    re.I,
)


def explicit_manufacturing_origin(evidence, value):
    """Accept a stated manufacture label and literal value in the same clause.

    Supported label languages are English, Spanish, German, French, Italian and
    Portuguese. The function deliberately rejects translated country names,
    headquarters, slogans, uncertain claims and a country in another sentence.
    """
    if (not isinstance(evidence, str) or not isinstance(value, str)
            or not value.strip() or len(value) > 80 or len(evidence) > 12000):
        return False
    evidence = " ".join(evidence.split())
    value = " ".join(value.split())
    if _DENIED_OR_UNCERTAIN.search(value):
        return False
    value_pattern = re.compile(r"\s*[:：=-]?\s*" + re.escape(value) + r"(?!\w)", re.I)
    for label in _ORIGIN_LABEL.finditer(evidence):
        stated = value_pattern.match(evidence, label.end())
        if not stated:
            continue
        # Do not let a negated phrase become positive just because its label was
        # recognized. Scope to the sentence/clause, not the entire document.
        before = re.split(r"[.!?;\n]", evidence[:label.start()])[-1]
        after = re.split(r"[.!?;\n]", evidence[stated.end():], maxsplit=1)[0]
        if (_DENIED_OR_UNCERTAIN.search(before) or _DENIED_OR_UNCERTAIN.search(after)
                or re.match(r"\s*(?:/|\bor\b|\bo\b|\bou\b|\boder\b|\boppure\b)", after, re.I)
                or (evidence[stated.end():].lstrip().startswith("?"))):
            continue
        return True
    return False


_UNIT_LABEL = re.compile(
    r"(?<!\w)(?:(?P<strong>"
    r"(?:n[uú]m(?:ero)?\.?|n(?:ro|o)?\.?[º°]?)\s*(?:de\s+)?s[eé]rie|"
    r"serial(?:\s+(?:number|no\.?))?|s\s*/\s*n|s\.\s*n\.|sn|pin|vin|"
    r"seriennummer|num[eé]ro\s+de\s+s[eé]rie|numero\s+di\s+serie"
    r")|(?P<bare>s[eé]rie))(?!\w)", re.I,
)
_COMMERCIAL_WORDS = re.compile(
    r"^(?:de|of|des|di)\s+(?:compactadores|excavadoras|tractores|productos|equipos|"
    r"m[aá]quinas|compactors|excavators|tractors|products|machines|equipment)\b", re.I,
)


def _identifier_prefix(text, value, *, brand=False):
    """Match complete identifiers with only spacing/hyphen format variation."""
    if not isinstance(value, str) or not value.strip():
        return None
    if not re.fullmatch(r"[\w\s/-]+", value) or "_" in value:
        return None
    characters = [char for char in value if char.isalnum()]
    if not characters:
        return None
    pattern = r"[\s/-]*".join(re.escape(char) for char in characters)
    # A slash is treated as an internal separator, not proof that the prefix of
    # ABC123/4 is the same unit as ABC123. Brand/model separation is different.
    pattern += r"(?!\w)" if brand else r"(?!\w|[-/][\w])"
    return re.match(pattern, text, re.I)


def _commercial_series(tail, brand, model):
    if _COMMERCIAL_WORDS.match(tail):
        return True
    # A bare 'serie' followed by the already identified model is a product
    # family label. 'Número de serie' never takes this exception.
    if _identifier_prefix(tail, model):
        return True
    aliases = {"cat": ("CAT", "Caterpillar"), "caterpillar": ("CAT", "Caterpillar"),
               "johndeere": ("John Deere", "Deere"), "deere": ("John Deere", "Deere"),
               "volvo": ("Volvo", "Volvo CE"), "volvoce": ("Volvo", "Volvo CE")}
    brand_key = re.sub(r"\W", "", str(brand or "")).casefold()
    for alias in aliases.get(brand_key, (brand,)):
        matched = _identifier_prefix(tail, alias, brand=True)
        if matched:
            following = tail[matched.end():].lstrip(" \t:-")
            if _identifier_prefix(following, model):
                return True
    return False


def has_conflicting_unit_reference(evidence, serial, *, brand=None, model=None):
    """Reject a labeled different/unknown unit, allowing commercial series text.

    A False result is *not* evidence of a unit match. In particular, 'No se
    encontró la serie ABC123' does not conflict with ABC123, but the caller must
    retain its separate denial guard before attributing any exact-unit facts.
    Every explicit label is checked: the requested ID elsewhere in a paragraph
    cannot excuse a second label that identifies another unit.
    """
    if not isinstance(evidence, str) or len(evidence) > 12000:
        return True
    for label in _UNIT_LABEL.finditer(evidence):
        tail = evidence[label.end():].lstrip(" \t\r\n:：#=-\"'")
        tail = re.sub(r"^(?:is|es|est|ist|[eé])\s+", "", tail, flags=re.I)
        if label.group("bare") and _commercial_series(tail, brand, model):
            continue
        if not _identifier_prefix(tail, serial):
            return True
    return False
