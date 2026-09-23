"""A fail-closed resolver for an adapter-authorised external catalogue.

The public IMC site is not a documented integration API.  This module therefore
does not fetch it, infer its schema, persist a match, or create a remote item.
An authorised adapter must supply the small, flat row contract used here.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence


_LABELS = ("type", "brand", "model")
_ID_FIELDS = tuple(f"{name}_id" for name in _LABELS)
_SPACE_OR_HYPHEN = re.compile(r"[\s\-\u2010-\u2015]+")
_NOT_FOUND = {
    "type": "Tipo de máquina no encontrado.",
    "brand": "Marca no encontrada.",
    "model": "Modelo no encontrado.",
}
_AMBIGUOUS = {
    "type": "Tipo de máquina ambiguo; requiere revisión.",
    "brand": "Marca ambigua; requiere revisión.",
    "model": "Modelo ambiguo; requiere revisión.",
}


def normalize_label(value: str) -> str:
    """Compare labels case/diacritic/space/hyphen-insensitively.

    This deliberately does not remove punctuation other than hyphens, so a
    decimal point remains meaningful: ``307.5`` does not become ``3075``.
    It also never strips suffixes, so ``L`` and a model without ``L`` differ.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _SPACE_OR_HYPHEN.sub(" ", without_marks.casefold()).strip()


def _empty_result(identity):
    originals = {}
    if isinstance(identity, Mapping):
        for name in _LABELS:
            value = identity.get(name)
            originals[name] = value if isinstance(value, str) else None
    else:
        originals = {name: None for name in _LABELS}
    return {
        "status": "missing",
        "field_errors": {},
        "original_texts": originals,
        "canonical_ids": {},
    }


def _valid_label(value):
    return isinstance(value, str) and bool(normalize_label(value)) and not any(char in value for char in "\r\n\x00")


def _valid_id(value):
    # IDs remain opaque strings.  In particular, neither int nor float is a
    # permitted substitute for a string with leading zeroes.
    return isinstance(value, str) and bool(value) and value == value.strip() and not any(char in value for char in "\r\n\x00")


def _alias_map(aliases):
    if aliases is None:
        return {}, {}
    if not isinstance(aliases, Mapping):
        return {}, {"aliases": "Los alias deben ser un objeto por campo."}
    unknown = set(aliases) - set(_LABELS)
    if unknown:
        return {}, {"aliases": "Los alias contienen campos no permitidos."}
    prepared = {}
    for field, values in aliases.items():
        if not isinstance(values, Mapping):
            return {}, {"aliases": f"Los alias de {field} deben ser un objeto."}
        prepared[field] = {}
        for source, target in values.items():
            if not _valid_label(source) or not _valid_label(target):
                return {}, {"aliases": f"Los alias de {field} deben contener textos válidos."}
            source_key, target_key = normalize_label(source), normalize_label(target)
            existing = prepared[field].get(source_key)
            if existing is not None and existing != target_key:
                return {}, {"aliases": f"Los alias de {field} son contradictorios."}
            prepared[field][source_key] = target_key
    return prepared, {}


def _canonical_label(field, value, aliases):
    normalized = normalize_label(value)
    return aliases.get(field, {}).get(normalized, normalized)


def resolve_catalogue(identity, rows, aliases=None):
    """Resolve one exact type/brand/model path without side effects.

    ``identity`` is ``{type, brand, model}``.  Each adapter row must contain
    those three text labels and the corresponding ``*_id`` opaque strings.
    The only accepted equivalence is normalization or an explicit alias passed
    by the caller.  A collision remains ambiguous for human review.
    """
    result = _empty_result(identity)
    if not isinstance(identity, Mapping):
        result["field_errors"]["identity"] = "La identidad debe ser un objeto con tipo, marca y modelo."
        return result
    unknown_identity = set(identity) - set(_LABELS)
    if unknown_identity:
        result["field_errors"]["identity"] = "La identidad contiene campos no permitidos."
    for field in _LABELS:
        if not _valid_label(identity.get(field)):
            result["field_errors"][field] = "Debe contener un texto válido."
    if result["field_errors"]:
        return result

    prepared_aliases, alias_errors = _alias_map(aliases)
    if alias_errors:
        result["field_errors"].update(alias_errors)
        return result
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        result["field_errors"]["rows"] = "El catálogo autorizado debe ser una lista de filas."
        return result

    valid_rows = []
    model_paths = {}
    type_labels = {}
    brand_labels = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            result["field_errors"]["rows"] = f"La fila {index} debe ser un objeto."
            continue
        missing = [field for field in (*_LABELS, *_ID_FIELDS) if field not in row]
        if missing:
            result["field_errors"]["rows"] = f"La fila {index} no contiene todos los campos requeridos."
            continue
        bad_label = next((field for field in _LABELS if not _valid_label(row[field])), None)
        bad_id = next((field for field in _ID_FIELDS if not _valid_id(row[field])), None)
        if bad_label:
            result["field_errors"]["rows"] = f"La fila {index} tiene {bad_label} inválido."
            continue
        if bad_id:
            result["field_errors"]["rows"] = f"La fila {index} tiene {bad_id} inválido; los identificadores deben ser texto opaco."
            continue
        parent = tuple(_canonical_label(field, row[field], prepared_aliases) for field in _LABELS)
        type_id, brand_id, model_id = (row[field] for field in _ID_FIELDS)
        prior_type = type_labels.get(type_id)
        if prior_type is not None and prior_type != parent[0]:
            result["field_errors"]["rows"] = "El catálogo contiene un identificador de tipo con etiquetas incompatibles."
            continue
        type_labels[type_id] = parent[0]
        # A brand ID may be used under different types, but must always retain
        # the same normalized brand text.
        prior_brand = brand_labels.get(brand_id)
        if prior_brand is not None and prior_brand != parent[1]:
            result["field_errors"]["rows"] = "El catálogo contiene un identificador de marca con etiquetas incompatibles."
            continue
        brand_labels[brand_id] = parent[1]
        # A reused model ID must bind the complete ID parent path and labels.
        # Comparing labels alone is unsafe because separate parent IDs may have
        # coincident display names.
        model_path = (type_id, brand_id, *parent)
        model_id = row["model_id"]
        prior = model_paths.get(model_id)
        if prior is not None and prior != model_path:
            result["field_errors"]["rows"] = "El catálogo contiene un identificador de modelo con padres incompatibles."
            continue
        model_paths[model_id] = model_path
        valid_rows.append((row, parent))

    if result["field_errors"]:
        return result
    # Identical adapter rows add no information and must not manufacture an
    # ambiguity merely because the adapter repeated them.
    deduplicated = []
    seen = set()
    for row, parent in valid_rows:
        key = tuple(row[field] for field in _ID_FIELDS) + parent
        if key not in seen:
            seen.add(key)
            deduplicated.append((row, parent))

    target = tuple(_canonical_label(field, identity[field], prepared_aliases) for field in _LABELS)
    type_rows = [(row, parent) for row, parent in deduplicated if parent[0] == target[0]]
    if not type_rows:
        result["field_errors"]["type"] = _NOT_FOUND["type"]
        return result
    type_ids = sorted({row["type_id"] for row, _ in type_rows})
    if len(type_ids) != 1:
        result["status"] = "ambiguous"
        result["field_errors"]["type"] = _AMBIGUOUS["type"]
        result["candidate_ids"] = type_ids
        return result
    brand_rows = [(row, parent) for row, parent in type_rows
                  if row["type_id"] == type_ids[0] and parent[1] == target[1]]
    if not brand_rows:
        result["field_errors"]["brand"] = _NOT_FOUND["brand"]
        return result
    brand_ids = sorted({row["brand_id"] for row, _ in brand_rows})
    if len(brand_ids) != 1:
        result["status"] = "ambiguous"
        result["field_errors"]["brand"] = _AMBIGUOUS["brand"]
        result["candidate_ids"] = brand_ids
        return result
    model_rows = [(row, parent) for row, parent in brand_rows
                  if row["brand_id"] == brand_ids[0] and parent[2] == target[2]]
    if not model_rows:
        result["field_errors"]["model"] = _NOT_FOUND["model"]
        return result
    model_ids = sorted({row["model_id"] for row, _ in model_rows})
    if len(model_ids) != 1:
        result["status"] = "ambiguous"
        result["field_errors"]["model"] = _AMBIGUOUS["model"]
        result["candidate_ids"] = model_ids
        return result
    row = model_rows[0][0]
    result["status"] = "matched"
    result["canonical_ids"] = {field: row[field] for field in _ID_FIELDS}
    return result
