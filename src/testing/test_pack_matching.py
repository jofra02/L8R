"""Tests for version-aware pack matching (src/core/pack_matching.py)."""

import pytest

from src.core.models import Component
from src.core.pack_matching import (
    derive_allowed_pack_keys,
    match_versions,
    match_versions_detailed,
)
from src.core.registry import GatewayPackInfo


def _pack(vendor="fortinet", product="fortigate", version="7.4",
          prefix="fgt74", device_type="fortios"):
    return GatewayPackInfo(
        vendor=vendor,
        product=product,
        version=version,
        prefix=prefix,
        device_type=device_type,
        display_name=f"{product} {version}",
        pack_key=f"{vendor}/{product}/{version}",
    )


def _managed_component(cid="fw1", vendor="fortinet", appliance="fortigate",
                       device_type="fortios", os_version="7.4.5", **mcp_extra):
    mcp = {
        "managed": True,
        "vendor": vendor,
        "appliance": appliance,
        "device_type": device_type,
        "os_version": os_version,
    }
    mcp.update(mcp_extra)
    return Component(id=cid, ref=cid, role="firewall", vendor=vendor, metadata={"mcp": mcp})


# ── match_versions ──────────────────────────────────────────────────────────

def test_exact_match():
    assert match_versions_detailed("7.4", ["7.2", "7.4", "7.6"]) == (["7.4"], "exact")


def test_exact_match_normalizes_v_prefix():
    assert match_versions("v7.4", ["7.4"]) == ["7.4"]


def test_major_minor_prefix_match():
    assert match_versions_detailed("7.4.5", ["7.2", "7.4", "7.6"]) == (["7.4"], "major_minor")


def test_major_only_matches_all_of_major():
    matched, rule = match_versions_detailed("7", ["6.2", "7.2", "7.4"])
    assert rule == "major"
    assert matched == ["7.2", "7.4"]


def test_no_match_falls_back_to_all():
    matched, rule = match_versions_detailed("9.9.9", ["7.2", "7.4"])
    assert rule == "fallback_all"
    assert matched == ["7.2", "7.4"]


def test_no_match_single_candidate_uses_it():
    matched, rule = match_versions_detailed("6.0", ["7.4"])
    assert rule == "fallback_all"
    assert matched == ["7.4"]


def test_missing_os_version_includes_all():
    matched, rule = match_versions_detailed("", ["7.2", "7.4"])
    assert rule == "no_version"
    assert matched == ["7.2", "7.4"]


def test_no_available_versions():
    assert match_versions("7.4", []) == []


# ── derive_allowed_pack_keys ────────────────────────────────────────────────

def test_scoped_to_matching_pack_version():
    packs = [_pack(version="7.4", prefix="fgt74"), _pack(version="7.6", prefix="fgt76")]
    components = [_managed_component(os_version="7.4.5")]
    assert derive_allowed_pack_keys(components, packs) == ["fortinet/fortigate/7.4"]


def test_multi_version_tenant_yields_both_keys():
    packs = [_pack(version="7.4", prefix="fgt74"), _pack(version="7.6", prefix="fgt76")]
    components = [
        _managed_component(cid="fw_a", os_version="7.4.5"),
        _managed_component(cid="fw_b", os_version="7.6.1"),
    ]
    assert derive_allowed_pack_keys(components, packs) == [
        "fortinet/fortigate/7.4",
        "fortinet/fortigate/7.6",
    ]


def test_no_managed_components_returns_none():
    packs = [_pack()]
    unmanaged = Component(id="srv1", ref="srv1", role="server", metadata={})
    assert derive_allowed_pack_keys([unmanaged], packs) is None
    assert derive_allowed_pack_keys([], packs) is None


def test_no_pack_metadata_returns_none():
    assert derive_allowed_pack_keys([_managed_component()], []) is None


def test_device_type_fallback_join():
    """Old metadata without vendor/appliance still resolves via device_type."""
    packs = [_pack()]
    component = _managed_component(vendor="", appliance="")
    assert derive_allowed_pack_keys([component], packs) == ["fortinet/fortigate/7.4"]


def test_missing_os_version_includes_all_product_versions():
    packs = [_pack(version="7.4", prefix="fgt74"), _pack(version="7.6", prefix="fgt76")]
    components = [_managed_component(os_version="")]
    assert derive_allowed_pack_keys(components, packs) == [
        "fortinet/fortigate/7.4",
        "fortinet/fortigate/7.6",
    ]


def test_unknown_device_skipped_but_known_scoped():
    packs = [_pack()]
    components = [
        _managed_component(cid="edr1", vendor="acme", appliance="boxos", device_type="boxos"),
        _managed_component(cid="fw1"),
    ]
    assert derive_allowed_pack_keys(components, packs) == ["fortinet/fortigate/7.4"]


def test_deduplicates_pack_keys():
    packs = [_pack()]
    components = [
        _managed_component(cid="fw_a", os_version="7.4.5"),
        _managed_component(cid="fw_b", os_version="7.4.7"),
    ]
    assert derive_allowed_pack_keys(components, packs) == ["fortinet/fortigate/7.4"]
