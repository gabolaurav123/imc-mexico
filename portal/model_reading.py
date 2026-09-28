"""Respect explicit limits of a model-label reading; never complete its text."""
import re
import unicodedata


_GAP = r"(?:ocult[oa]|tapad[oa]|cortad[oa]|ilegible|borros[oa]|incomplet[oa]|no (?:visible|legible|confirmable)|fuera (?:del? |de la )?(?:encuadre|foto)|hidden|covered|cropped|unreadable|missing|obscured|occluded)"
_RELATION = r"(?:\s+(?:(?:del?|de la) (?:rotulo|modelo|etiqueta)|of (?:the )?(?:model|label)))?(?:\s+(?:esta|es|se ve|se lee|is))?\s+"
_START_GAP = re.compile(r"\b(?:inicio|comienzo|prefijo|extremo izquierdo|parte inicial|beginning|prefix|left edge)" + _RELATION + _GAP + r"\b")
_END_GAP = re.compile(r"\b(?:final|sufijo|extremo derecho|caracteres finales|suffix|right edge|ending)" + _RELATION + _GAP + r"\b")
_PARTIAL_LABEL = re.compile(
    r"\b(?:rotulo(?: del modelo)?|modelo|model label|label)"
    r"(?:\s+[\"«“][^\"»”\n]{1,48}[\"»”])?(?:\s+(?:esta|es|se ve|se lee|is))?\s+"
    r"(?:parcial(?:mente)?|incomplet[oa]|partial(?:ly)?|incomplete|" + _GAP + r")\b"
    r"|\bfragmento (?:del? |de la )?(?:rotulo|modelo|etiqueta)\b"
)


def _evidence(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join("".join(char for char in value if not unicodedata.combining(char)).split())


def partial_model_label(evidence):
    """Only explicit label/edge limitations count, never a short model code."""
    text = _evidence(evidence)
    return bool(_START_GAP.search(text) or _END_GAP.search(text) or _PARTIAL_LABEL.search(text))


def allows_model_prefix_hint(evidence):
    """A missing beginning cannot constrain model discovery with startswith."""
    text = _evidence(evidence)
    return not _START_GAP.search(text) and (not _PARTIAL_LABEL.search(text) or bool(_END_GAP.search(text)))
