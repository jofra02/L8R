"""Deterministic attribute validation against asset-type definitions.

Writes validate against the latest type schema version; reads tolerate
unknown/legacy keys (they are never dropped). ``allowed_extra_keys`` carries
the keys already stored on the asset so legacy data keeps validating.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from src.assets.schema import AssetTypeDefinition, TypeFieldDef

# Keys always tolerated (adapter bookkeeping).
INTERNAL_ATTRIBUTE_KEYS = frozenset({"legacy_role"})


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _check_value(field: TypeFieldDef, value: Any) -> Optional[str]:
    """Return an error string or None. Deterministic, never raises."""
    t = field.type
    v = field.validation

    if t == "string":
        if not isinstance(value, str):
            return "must be a string"
        if v and v.max_length is not None and len(value) > v.max_length:
            return f"exceeds max_length {v.max_length}"
        if v and v.pattern and not re.search(v.pattern, value):
            return f"does not match pattern {v.pattern}"
    elif t == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return "must be an integer"
        if v and v.min is not None and value < v.min:
            return f"below min {v.min}"
        if v and v.max is not None and value > v.max:
            return f"above max {v.max}"
    elif t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "must be a number"
        if v and v.min is not None and value < v.min:
            return f"below min {v.min}"
        if v and v.max is not None and value > v.max:
            return f"above max {v.max}"
    elif t == "boolean":
        if not isinstance(value, bool):
            return "must be a boolean"
    elif t == "date":
        try:
            date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return "must be an ISO date (YYYY-MM-DD)"
    elif t == "datetime":
        try:
            _parse_datetime(value)
        except (TypeError, ValueError):
            return "must be an ISO datetime"
    elif t == "enum":
        if value not in (field.enum or []):
            return f"must be one of {field.enum}"
    elif t == "string_list":
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            return "must be a list of strings"
    elif t == "ip":
        try:
            ipaddress.ip_address(str(value))
        except ValueError:
            return "must be a valid IP address"
    elif t == "json":
        if not isinstance(value, (dict, list, str, int, float, bool)) and value is not None:
            return "must be JSON-serializable"
    return None


def validate_attributes(
    type_def: AssetTypeDefinition,
    attributes: Dict[str, Any],
    *,
    allowed_extra_keys: Iterable[str] = (),
    apply_defaults: bool = True,
) -> Tuple[Dict[str, Any], List[str]]:
    """Validate and complete *attributes* against *type_def*.

    Returns (normalized_attributes, errors). Errors are field-scoped strings
    suitable for a 422 validation_error detail.
    """
    errors: List[str] = []
    out = dict(attributes or {})
    fields = type_def.field_map()

    tolerated: Set[str] = set(INTERNAL_ATTRIBUTE_KEYS) | set(allowed_extra_keys)
    if not type_def.open_attributes:
        for key in out:
            if key not in fields and key not in tolerated:
                errors.append(f"attributes.{key}: not declared for type '{type_def.type_id}'")

    for key, field in fields.items():
        if key not in out or out[key] is None:
            if field.required and apply_defaults:
                out[key] = field.default
            continue
        err = _check_value(field, out[key])
        if err:
            errors.append(f"attributes.{key}: {err}")

    return out, errors


def sensitive_keys(type_def: AssetTypeDefinition) -> Set[str]:
    return {f.key for f in type_def.fields if f.sensitive}


def filterable_field_defs(types: Dict[str, AssetTypeDefinition]) -> Dict[str, TypeFieldDef]:
    """Union of filterable attribute fields across type definitions.

    When the same key is filterable in several types the first definition
    wins (used only for value coercion in query filters).
    """
    out: Dict[str, TypeFieldDef] = {}
    for type_def in types.values():
        for f in type_def.fields:
            if f.filterable and f.key not in out:
                out[f.key] = f
    return out


def coerce_filter_value(field: TypeFieldDef, raw: str) -> Any:
    """Coerce a query-string filter value to the field's JSON type."""
    if field.type == "integer":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return raw
    if field.type == "number":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return raw
    if field.type == "boolean":
        return str(raw).lower() in ("true", "1", "yes")
    return raw
