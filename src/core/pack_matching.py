"""Version-aware appliance-pack matching.

Maps a tenant's managed devices (``Component.metadata["mcp"]``: vendor,
appliance, device_type, os_version) to the gateway pack versions whose tools
the Engineer should see. The result is a set of ``pack_key`` strings
("vendor/product/version") used to scope tool_catalog searches.

Matching is deliberately over-inclusive on ambiguity: pack tools are
read-only, and silently under-including versions breaks investigations.
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional, Sequence, Tuple

from src.core.registry import GatewayPackInfo

logger = logging.getLogger(__name__)


def _normalize(version: str) -> str:
    return (version or "").strip().lstrip("vV").strip()


def _segments(version: str) -> List[str]:
    return [s for s in _normalize(version).split(".") if s]


def match_versions_detailed(
    os_version: str, available_versions: Sequence[str]
) -> Tuple[List[str], str]:
    """Deterministic device-version -> pack-version resolution.

    Returns (matched_versions, rule) where rule is one of:
      "exact"        — pack version equals the device version.
      "major_minor"  — pack version equals the device's major.minor.
      "major"        — major-only device version; every pack sharing the major.
      "no_version"   — empty os_version; all available versions.
      "fallback_all" — no rule matched; all available versions (over-inclusion
                       is deliberate: tools are read-only, under-inclusion
                       silently breaks investigations).
    """
    versions = list(available_versions)
    if not versions:
        return [], "fallback_all"

    normalized = _normalize(os_version)
    if not normalized:
        return versions, "no_version"

    exact = [v for v in versions if _normalize(v) == normalized]
    if exact:
        return exact, "exact"

    segs = _segments(normalized)
    if len(segs) >= 2:
        major_minor = ".".join(segs[:2])
        prefix_match = [v for v in versions if ".".join(_segments(v)[:2]) == major_minor]
        if prefix_match:
            return prefix_match, "major_minor"

    if len(segs) == 1:
        major_match = [v for v in versions if _segments(v)[:1] == segs]
        if major_match:
            return major_match, "major"

    return versions, "fallback_all"


def match_versions(os_version: str, available_versions: Sequence[str]) -> List[str]:
    return match_versions_detailed(os_version, available_versions)[0]


def derive_allowed_pack_keys(
    components: Iterable,
    packs: Sequence[GatewayPackInfo],
) -> Optional[List[str]]:
    """Allowed pack_keys for a tenant, from its managed components.

    Returns None (-> unscoped search) when the tenant has no managed
    components or no pack metadata is available.
    """
    if not packs:
        return None

    managed = []
    for component in components or []:
        mcp = (getattr(component, "metadata", None) or {}).get("mcp") or {}
        if mcp.get("managed"):
            managed.append((component, mcp))
    if not managed:
        return None

    allowed: List[str] = []
    for component, mcp in managed:
        device_id = getattr(component, "id", "?")
        vendor = (mcp.get("vendor") or "").lower()
        appliance = (mcp.get("appliance") or "").lower()
        device_type = (mcp.get("device_type") or "").lower()
        os_version = mcp.get("os_version") or ""

        candidates = [
            p for p in packs
            if p.vendor.lower() == vendor and p.product.lower() == appliance
        ]
        if not candidates and device_type:
            # Metadata predating the vendor/appliance fields: join on device_type.
            candidates = [p for p in packs if p.device_type.lower() == device_type]
        if not candidates:
            logger.warning(
                f"pack_matching: device '{device_id}' (vendor={vendor or '?'}, "
                f"appliance={appliance or '?'}, device_type={device_type or '?'}) "
                f"matches no gateway pack."
            )
            continue

        by_version = {p.version: p for p in candidates}
        matched_versions, rule = match_versions_detailed(os_version, list(by_version))
        if rule == "no_version":
            logger.info(
                f"pack_matching: device '{device_id}' has no os_version — "
                f"including all versions {sorted(by_version)} of "
                f"{candidates[0].vendor}/{candidates[0].product}."
            )
        elif rule in ("major", "fallback_all"):
            logger.warning(
                f"pack_matching: device '{device_id}' os_version='{os_version}' "
                f"resolved by rule '{rule}' against pack versions "
                f"{sorted(by_version)} — including {sorted(matched_versions)}."
            )

        allowed.extend(by_version[v].pack_key for v in matched_versions)

    if not allowed:
        return None
    # Deduplicate, stable order.
    return list(dict.fromkeys(allowed))
