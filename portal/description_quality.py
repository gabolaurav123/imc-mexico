"""Minimum structure for automatic technical prose, shared by generation and readiness."""
import re


def has_technical_description(value, provenance=None):
    """Require three distinct useful clauses without rewriting owner-approved copy.

    This is a structural floor, not a factual or semantic validator. The system's
    deterministic summary of identity, specifications and age is not model prose.
    Both paragraphs and line breaks work for the technical description.
    """
    if not isinstance(value, str) or not value.strip():
        return False
    meta = provenance if isinstance(provenance, dict) else {}
    if meta.get("source") == "user" or meta.get("review") == "confirmed":
        return True
    if meta.get("source") == "system":
        return False
    if len(value.strip()) < 100:
        return False
    clauses = set()
    for clause in re.split(r"(?<=[.!?])\s+|[\r\n]+", value):
        clause = " ".join(clause.split()).strip(" -•")
        if (not clause or re.match(r"^(?:datos principales|año aproximado|rango de años?)\s*:", clause, re.I)
                or re.match(r"^Características de referencia del modelo\s*[:.]", clause, re.I)
                or re.search(r"\b(?:pendiente\w*|por confirmar|sin datos|no disponible)\b", clause, re.I)
                or re.match(r"^(?:Maquinaria presentada|Fotografías disponibles)\b", clause, re.I)):
            continue
        words = re.findall(r"[^\W\d_]+", clause, re.UNICODE)
        if len(words) >= 4 and len(clause) >= 20:
            clauses.add(" ".join(clause.casefold().split()).rstrip(".!?"))
    return len(clauses) >= 3
