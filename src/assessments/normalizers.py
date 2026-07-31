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


# --- License normalization -------------------------------------------------
#
# Deterministic cross-vendor license model stored as `attributes.licenses`:
#   {key, label, category, status, state, expires, entitlement, seats,
#    version, last_update, details}
# category: signature | cloud_service | support_contract | registration |
#           capacity | platform
# state:    ok | expired | none | unknown — a pure map from the SOURCE
#           status; nothing time-relative is baked in (the UI derives
#           "expiring soon"/"past expiry" from `expires` at render time).
# Unknown shapes are never dropped: they surface as state "unknown" with
# the raw entry preserved in `details`.

_LICENSE_STATE_MAP = {
    "licensed": "ok",
    "registered": "ok",
    "valid": "ok",
    "vm_valid": "ok",
    "free_license": "ok",
    "connected": "ok",
    "active": "ok",
    "expired": "expired",
    "vm_expired": "expired",
    "vm_eval_expired": "expired",
    "no_license": "none",
    "cloud_na": "none",
    "disconnected": "none",
    "unregistered": "none",
    "unregistrable": "none",
    "registrable": "none",
}


def _license_state(status: Any) -> str:
    if status is None or status == "":
        return "unknown"
    return _LICENSE_STATE_MAP.get(str(status).lower(), "unknown")


def _license_label(key: str) -> str:
    return key.replace("_", " ").replace(".", " · ").title()


def _license_iso(value: Any) -> Any:
    if value in (None, "", 0):
        return None
    from src.assets.enrichment.mappings import _to_iso
    return _to_iso(value, date_only=False)


def _license_entry(key: str, category: str, source: Dict[str, Any], *,
                   label: str | None = None, status: Any = None,
                   details: Dict[str, Any] | None = None) -> Dict[str, Any]:
    raw_status = status if status is not None else source.get("status")
    seats = None
    if isinstance(source.get("max"), (int, float)) or isinstance(source.get("used"), (int, float)):
        seats = {"used": source.get("used"), "max": source.get("max")}
    return {
        "key": key,
        "label": label or _license_label(key),
        "category": category,
        "status": raw_status,
        "state": _license_state(raw_status),
        "expires": _license_iso(source.get("expires")),
        "entitlement": source.get("entitlement"),
        "seats": seats,
        "version": source.get("version"),
        "last_update": _license_iso(source.get("last_update")),
        "details": details or {},
    }


_FGT_SIGNATURE_TYPES = ("downloaded_fds_object", "fds_version_object")
_FGT_CLOUD_TYPES = (
    "live_fortiguard_service", "live_cloud_service",
    "account_level_live_cloud_service", "cloud_service_status",
    "functionality_enabling",
)


def _fgt_category(value: Dict[str, Any]) -> str:
    vtype = str(value.get("type") or "")
    if vtype == "platform":
        return "platform"
    if vtype in _FGT_SIGNATURE_TYPES or vtype.startswith("downloaded_fds"):
        return "signature"
    if vtype in _FGT_CLOUD_TYPES:
        return "cloud_service"
    # Unknown future type: version/db fields smell like a signature package.
    return "signature" if "version" in value else "cloud_service"


@register_normalizer("fortigate.license_status")
def fortigate_license_status(raw: Any) -> Dict[str, Any]:
    """FortiOS /license/status -> monitor envelope + `normalized` entries.

    The envelope is identical to fortigate.monitor_results so existing
    `license.results` mappings keep working; `normalized` feeds
    `attributes.licenses`.
    """
    env = _fortios_envelope(raw)
    if "error" in env:
        return env
    results = env["results"]
    normalized: list = []
    if not isinstance(results, dict):
        env["normalized"] = normalized
        return env

    for key, value in sorted(results.items()):
        if not isinstance(value, dict):
            continue

        if key == "forticare":
            reg_status = value.get("registration_status") or value.get("status")
            normalized.append(_license_entry(
                key, "registration", value, label="FortiCare Registration",
                status=reg_status,
                details={k: value[k] for k in ("account", "company", "industry", "status")
                         if value.get(k) not in (None, "")},
            ))
            support = value.get("support")
            if isinstance(support, dict):
                for level_key, level in sorted(support.items()):
                    if isinstance(level, dict) and level:
                        normalized.append(_license_entry(
                            f"forticare.support.{level_key}", "support_contract", level,
                            label=f"FortiCare {level_key.title()} Support",
                            details={"support_level": level.get("support_level")},
                        ))
            continue

        if key == "fortiguard":
            connected = value.get("connected")
            status = value.get("status")
            if connected is not None:
                status = "connected" if connected else "disconnected"
            normalized.append(_license_entry(
                key, "cloud_service", value, label="FortiGuard Connectivity",
                status=status,
                details={k: v for k, v in {
                    "server_address": value.get("server_address"),
                    "last_connection_success": _license_iso(value.get("last_connection_success")),
                    "next_scheduled_update": _license_iso(value.get("next_scheduled_update")),
                }.items() if v is not None},
            ))
            continue

        # Nested definition containers (ot_detection.{detect,patch}_definitions,
        # iot_detection.definitions) flatten to their own signature entries.
        nested = {nk: nv for nk, nv in value.items()
                  if isinstance(nv, dict) and ("status" in nv or "version" in nv)
                  and nk not in ("engine", "support")}

        has_own_body = "status" in value or "max" in value or "used" in value
        if has_own_body:
            if "max" in value or "used" in value:
                category = "platform" if value.get("type") == "platform" else "capacity"
            else:
                category = _fgt_category(value)
            details: Dict[str, Any] = {}
            for extra in ("db_status", "last_update_result_status", "account", "domain"):
                if value.get(extra) not in (None, ""):
                    details[extra] = value[extra]
            normalized.append(_license_entry(key, category, value, details=details))
        for nk, nv in sorted(nested.items()):
            normalized.append(_license_entry(f"{key}.{nk}", "signature", nv))
        if not has_own_body and not nested:
            # Unknown shape — keep it visible, never drop.
            normalized.append(_license_entry(
                key, "cloud_service", value, status=value.get("status"),
                details={"raw": value},
            ))

    env["normalized"] = normalized
    return env


_FEDR_SEAT_CLASSES = (
    ("workstations", "workstationsCollectorsInUse", "workstationCollectorsLicenseCapacity"),
    ("servers", "serverCollectorsInUse", "serverCollectorsLicenseCapacity"),
    ("iot", "iotDevicesInUse", "iotDevicesLicenseCapacity"),
)


@register_normalizer("fortiedr.system_summary")
def fortiedr_system_summary(raw: Any) -> Dict[str, Any]:
    """FortiEDR list-system-summary -> fortiedr.results envelope +
    `normalized` license entries + `capacity` dict (feeds
    attributes.license_capacity)."""
    env = fortiedr_results(raw)
    if "error" in env:
        return env
    r = env["results"]
    if not isinstance(r, dict):
        return env
    normalized: list = []
    capacity: Dict[str, Any] = {}

    lic_type = r.get("licenseType")
    expiration = r.get("licenseExpirationDate")
    if lic_type or expiration:
        normalized.append(_license_entry(
            "console_license", "platform",
            {"expires": expiration},
            label="Console License", status="active",
            details={k: v for k, v in {
                "license_type": lic_type,
                "features": r.get("licenseFeatures"),
                "customer": r.get("customerName"),
                "serial_number": r.get("serialNumber"),
            }.items() if v not in (None, "", [])},
        ))

    for cls, used_key, max_key in _FEDR_SEAT_CLASSES:
        used, cap = r.get(used_key), r.get(max_key)
        if used is None and cap is None:
            continue
        capacity[cls] = {"used": used, "max": cap}
        normalized.append(_license_entry(
            cls, "capacity", {"used": used, "max": cap},
            label=f"{cls.title()} Seats", status="active",
        ))
    if r.get("registeredCollectors") is not None:
        capacity["registered_collectors"] = r.get("registeredCollectors")

    env["normalized"] = normalized
    env["capacity"] = capacity
    return env


@register_normalizer("fortiedr.license_status_dashboard")
def fortiedr_license_status_dashboard(raw: Any) -> Dict[str, Any]:
    """FortiEDR /api/dashboard/license-status-per-organization.

    The org-scoped license source that hosted consoles actually serve
    (management-rest admin/* and organizations both 403 for org-scoped API
    users; the dashboard family auto-scopes from the basic-auth org).
    Response: {licenseType, expirationDate "31-Dec-2026",
    numberOfDaysRemaining, usedStorage}.
    """
    env = fortiedr_results(raw)
    if "error" in env:
        return env
    r = env["results"]
    normalized: list = []
    if isinstance(r, dict) and (r.get("licenseType") or r.get("expirationDate")):
        normalized.append(_license_entry(
            "console_license", "platform",
            {"expires": r.get("expirationDate")},
            label="Console License", status="active",
            details={k: v for k, v in {
                "license_type": r.get("licenseType"),
                "days_remaining": r.get("numberOfDaysRemaining"),
                "used_storage": r.get("usedStorage"),
            }.items() if v is not None},
        ))
    env["normalized"] = normalized
    return env


@register_normalizer("fortiedr.license_capacity_dashboard")
def fortiedr_license_capacity_dashboard(raw: Any) -> Dict[str, Any]:
    """FortiEDR /api/dashboard/license-capacity-per-organization.

    Response: {"result": [{"name": "endpoints", "inUse": N, "remaining": M}]}
    -> `capacity` dict {name: {used, max: inUse+remaining}} for
    attributes.license_capacity (auto-scoped, works on hosted consoles).
    """
    env = fortiedr_results(raw)
    if "error" in env:
        return env
    rows = env["results"]
    if isinstance(rows, dict):
        rows = [rows]
    capacity: Dict[str, Any] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not row.get("name"):
                continue
            used = row.get("inUse")
            remaining = row.get("remaining")
            total = (used or 0) + (remaining or 0) if (used is not None or remaining is not None) else None
            capacity[str(row["name"])] = {"used": used, "max": total}
    env["capacity"] = capacity
    return env


@register_normalizer("fortiedr.organizations")
def fortiedr_organizations(raw: Any) -> Dict[str, Any]:
    """FortiEDR list-organizations -> fortiedr.results envelope +
    `normalized` per-org license/seat entries + `expiration` (earliest org
    expiry) + aggregated `capacity`.

    This is the org-scoped license source: hosted multi-org consoles 403 on
    admin/list-system-summary but serve this endpoint.
    """
    env = fortiedr_results(raw)
    if "error" in env:
        return env
    orgs = env["results"]
    if isinstance(orgs, dict):
        orgs = [orgs]
    if not isinstance(orgs, list):
        return env

    normalized: list = []
    capacity: Dict[str, Any] = {}
    earliest: str | None = None

    seat_fields = (
        ("workstations", "workstationsInUse", "workstationsAllocated"),
        ("servers", "serversInUse", "serversAllocated"),
        ("iot", "iotInUse", "iotAllocated"),
    )
    feature_keys = ("edr", "forensics", "vulnerabilityAndIoT", "eXtendedDetection")

    for org in orgs:
        if not isinstance(org, dict):
            continue
        name = org.get("name") or str(org.get("organizationId") or "organization")
        expires_iso = _license_iso(org.get("expirationDate"))
        if expires_iso and (earliest is None or expires_iso < earliest):
            earliest = expires_iso
        features = {k: org[k] for k in feature_keys if k in org}
        normalized.append(_license_entry(
            f"org:{name}", "platform", {"expires": org.get("expirationDate")},
            label=f"Organization {name}", status="active",
            details={k: v for k, v in {
                "organization": name,
                "serial_number": org.get("serialNumber"),
                "is_admin_account": org.get("isAdminAccount"),
                "features": features or None,
                "repository_add_ons": org.get("repositoryAddOns"),
            }.items() if v is not None},
        ))
        for cls, used_key, max_key in seat_fields:
            used, cap = org.get(used_key), org.get(max_key)
            if used is None and cap is None:
                continue
            normalized.append(_license_entry(
                f"org:{name}/{cls}", "capacity", {"used": used, "max": cap},
                label=f"{name} — {cls.title()} Seats", status="active",
                details={"organization": name},
            ))
            agg = capacity.setdefault(cls, {"used": 0, "max": 0})
            agg["used"] += used or 0
            agg["max"] += cap or 0

    env["normalized"] = normalized
    env["expiration"] = earliest
    env["capacity"] = capacity
    return env
