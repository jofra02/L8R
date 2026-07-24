"""Versioned pack layout contract tests.

Packs live at ``vendors/<vendor>/<appliance>/<version>/``. Two versions of the
same appliance share a device_type (same tenant inventory) but mount under
distinct prefixes so their tool names never collide; duplicate prefixes are a
startup error.
"""

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from gateway.app import build_gateway
from gateway.vendor_pack import discover_packs

MINIMAL_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Dummy", "version": "v1"},
    "servers": [{"url": "/"}],
    "paths": {
        "/api/status": {
            "get": {
                "operationId": "get_status",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}


def _write_pack(vendors_root: Path, vendor: str, appliance: str, version: str, prefix: str):
    pack_dir = vendors_root / vendor / appliance / version
    (pack_dir / "specs" / "mgmt").mkdir(parents=True)
    (pack_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "display_name": f"{appliance} {version}",
                "prefix": prefix,
                "device_type": "dummyos",
                "spec_glob": "*.json",
            }
        ),
        encoding="utf-8",
    )
    (pack_dir / "specs" / "mgmt" / "dummy_core.json").write_text(
        json.dumps(MINIMAL_SPEC), encoding="utf-8"
    )


def test_discover_defaults_identity_from_directory_layout(tmp_path):
    _write_pack(tmp_path, "acme", "boxos", "1.0", "box10")
    packs = discover_packs(tmp_path)
    assert len(packs) == 1
    pack = packs[0]
    assert (pack.vendor, pack.name, pack.version) == ("acme", "boxos", "1.0")
    assert pack.pack_key == "acme/boxos/1.0"
    assert pack.qualified_name == "acme/boxos/1.0"


def test_unversioned_layout_is_skipped(tmp_path, caplog):
    pack_dir = tmp_path / "acme" / "boxos"
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.yaml").write_text(
        yaml.safe_dump({"display_name": "Box", "prefix": "box", "device_type": "dummyos"}),
        encoding="utf-8",
    )
    packs = discover_packs(tmp_path)
    assert packs == []


def test_two_versions_same_device_type_mount_concurrently(tmp_path):
    _write_pack(tmp_path, "acme", "boxos", "1.0", "box10")
    _write_pack(tmp_path, "acme", "boxos", "2.0", "box20")

    gateway = build_gateway(vendors_root=tmp_path)
    tools = asyncio.run(gateway.get_tools())

    box10 = [n for n in tools if n.startswith("box10_")]
    box20 = [n for n in tools if n.startswith("box20_")]
    assert box10 and box20
    # Same leaf tool set, different version prefixes.
    assert {n.removeprefix("box10_") for n in box10} == {
        n.removeprefix("box20_") for n in box20
    }


def test_duplicate_prefix_fails_fast(tmp_path):
    _write_pack(tmp_path, "acme", "boxos", "1.0", "box")
    _write_pack(tmp_path, "acme", "boxos", "2.0", "box")

    with pytest.raises(RuntimeError, match="Duplicate mount prefix 'box'"):
        build_gateway(vendors_root=tmp_path)
