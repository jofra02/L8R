"""Named evidence normalizers.

Definitions reference normalizers by name (e.g. ``fortigate.cmdb_results``);
the registry resolves them at sync-validation time so a typo in a YAML file
fails fast instead of at run time.

A normalizer receives the raw (already sanitized) tool payload and returns a
compact JSON-serializable structure the evaluation rules consume. Normalizers
must be pure and defensive: malformed device output yields
``{"error": "..."}`` rather than raising.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

_NORMALIZERS: Dict[str, Callable[[Any], Dict[str, Any]]] = {}

# FortiOS REST envelope keys worth keeping alongside the results
_FORTIOS_META_KEYS = ("version", "build", "serial", "vdom", "status", "http_status")


def register_normalizer(name: str):
    def deco(fn: Callable[[Any], Dict[str, Any]]):
        if name in _NORMALIZERS:
            raise ValueError(f"duplicate normalizer '{name}'")
        _NORMALIZERS[name] = fn
        return fn
    return deco


def get_normalizer(name: str) -> Callable[[Any], Dict[str, Any]]:
    try:
        return _NORMALIZERS[name]
    except KeyError:
        raise KeyError(f"unknown normalizer '{name}'") from None


def known_normalizers() -> list[str]:
    return sorted(_NORMALIZERS)


def _parse_payload(raw: Any) -> Any:
    """Gateway tools return flattened text; try to recover the JSON body."""
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
    return raw


def _fortios_envelope(raw: Any) -> Dict[str, Any]:
    payload = _parse_payload(raw)
    if isinstance(payload, dict):
        results = payload.get("results", payload)
        meta = {k: payload[k] for k in _FORTIOS_META_KEYS if k in payload}
        return {"results": results, "meta": meta}
    if isinstance(payload, list):
        return {"results": payload, "meta": {}}
    return {"error": f"unparseable payload ({type(payload).__name__})",
            "raw_excerpt": str(payload)[:500]}


@register_normalizer("fortigate.cmdb_results")
def fortigate_cmdb_results(raw: Any) -> Dict[str, Any]:
    """FortiOS cmdb GET envelope -> {results, meta}."""
    return _fortios_envelope(raw)


@register_normalizer("fortigate.monitor_results")
def fortigate_monitor_results(raw: Any) -> Dict[str, Any]:
    """FortiOS monitor GET envelope -> {results, meta} (results may be a dict)."""
    return _fortios_envelope(raw)


@register_normalizer("passthrough")
def passthrough(raw: Any) -> Dict[str, Any]:
    """Parse the payload but keep its native shape under 'results'.

    For APIs without a response envelope (e.g. FortiEDR returns bare JSON
    arrays/objects).
    """
    payload = _parse_payload(raw)
    if isinstance(payload, (dict, list)):
        return {"results": payload, "meta": {}}
    return {"error": f"unparseable payload ({type(payload).__name__})",
            "raw_excerpt": str(payload)[:500]}


@register_normalizer("fortiedr.results")
def fortiedr_results(raw: Any) -> Dict[str, Any]:
    """FortiEDR management REST -> {results, meta}.

    Handles both observed response shapes: a bare JSON array/object and the
    ``{"result": ...}`` envelope returned by hosted consoles.
    """
    payload = _parse_payload(raw)
    if isinstance(payload, dict) and "result" in payload:
        payload = payload["result"]
    if isinstance(payload, (dict, list)):
        return {"results": payload, "meta": {}}
    return {"error": f"unparseable payload ({type(payload).__name__})",
            "raw_excerpt": str(payload)[:500]}
