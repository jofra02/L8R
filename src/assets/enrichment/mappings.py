"""Deterministic path extraction, transforms and merge policy.

Everything here is pure: no I/O, no LLM. Extraction paths are dotted with
optional [N] indices; a trailing [*] yields a list (items selectors).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.assets.schema import FieldMapping

logger = logging.getLogger(__name__)

_SEGMENT = re.compile(r"^(?P<key>[^\[\]]*)(?P<idx>(\[(\d+|\*)\])*)$")


def extract_path(data: Any, path: str) -> Any:
    """Resolve a dotted path (``a.b[0].c``, trailing ``[*]`` -> list).

    Returns None when any segment is missing — never raises.
    """
    if path in ("", "."):
        return data
    current = data
    for segment in path.split("."):
        if current is None:
            return None
        m = _SEGMENT.match(segment)
        if not m:
            return None
        key = m.group("key")
        if key:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        for idx in re.findall(r"\[(\d+|\*)\]", segment):
            if idx == "*":
                return current if isinstance(current, list) else (
                    [current] if current is not None else []
                )
            if not isinstance(current, list):
                return None
            i = int(idx)
            current = current[i] if i < len(current) else None
    return current


def extract_items(data: Any, path: str) -> List[Any]:
    value = extract_path(data, path)
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def apply_transform(value: Any, transform: Optional[str],
                    value_map: Optional[Dict[str, Any]] = None) -> Any:
    if value is None:
        return None
    if value_map is not None:
        return value_map.get(str(value), value)
    if transform is None:
        return value
    if transform == "lowercase":
        return str(value).lower()
    if transform == "first":
        if isinstance(value, list):
            return value[0] if value else None
        return value
    if transform == "join":
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return str(value)
    if transform == "to_datetime":
        return _to_iso(value, date_only=False)
    if transform == "to_date":
        return _to_iso(value, date_only=True)
    return value


def _to_iso(value: Any, *, date_only: bool) -> Optional[str]:
    dt: Optional[datetime] = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Epoch: >1e12 means milliseconds (FortiEDR uses epoch ms).
        seconds = value / 1000.0 if value > 1e12 else float(value)
        try:
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            return _to_iso(int(raw), date_only=date_only)
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            # FortiEDR styles: "2026-07-29 10:22:33", "29-Jul-2026, 10:22:33",
            # and the dashboard's bare "31-Dec-2026".
            for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y, %H:%M:%S", "%d-%b-%Y"):
                try:
                    dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
    if dt is None:
        return None
    return dt.date().isoformat() if date_only else dt.isoformat()


_EMPTY = (None, "", [], {})


def merge_field(asset, mapping: FieldMapping, value: Any, *,
                pack_id: str, run_id: str) -> bool:
    """Write one mapped value onto the asset honoring policy + provenance.

    Returns True when the asset changed. manual_wins (default): a field
    whose current value is non-empty and whose provenance is manual (or
    unknown — pre-existing data is treated as manual) is never overwritten.
    """
    value = apply_transform(value, mapping.transform, mapping.value_map)
    if value is None:
        return False

    target = mapping.target
    if target.startswith("attributes."):
        key = target[len("attributes."):]
        current = (asset.attributes or {}).get(key)
    else:
        current = getattr(asset, target)

    if mapping.policy == "manual_wins" and current not in _EMPTY:
        prov = (asset.provenance or {}).get(target)
        if prov is None or prov.get("source") == "manual":
            return False

    if current == value:
        return False

    if target.startswith("attributes."):
        attrs = dict(asset.attributes or {})
        attrs[target[len("attributes."):]] = value
        asset.attributes = attrs
    else:
        setattr(asset, target, value)

    prov_map = dict(asset.provenance or {})
    prov_map[target] = {
        "source": "discovered",
        "pack_id": pack_id,
        "run_id": run_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    asset.provenance = prov_map
    return True


def apply_mappings(asset, mappings: List[FieldMapping], source: Any, *,
                   pack_id: str, run_id: str) -> Tuple[int, List[str]]:
    """Apply a mapping list against a source object. Returns (changed, diffs)."""
    changed = 0
    fields: List[str] = []
    for mapping in mappings:
        value = extract_path(source, mapping.source)
        if merge_field(asset, mapping, value, pack_id=pack_id, run_id=run_id):
            changed += 1
            fields.append(mapping.target)
    return changed, fields
