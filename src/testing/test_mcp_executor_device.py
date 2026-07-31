"""Device selector canonicalization (in-memory sqlite).

The gateway registry is keyed by asset id; ``_canonicalize_device`` maps a
caller-supplied ref slug to the id, tenant-scoped. Ids pass through, unknown
values pass through untouched (they may address hand-maintained gateway
inventory entries), and a DB failure degrades to passthrough.

Run: uv run pytest src/testing/test_mcp_executor_device.py
"""

import uuid

import pytest

import src.core.database as database_mod
from src.core.mcp_executor import _canonicalize_device
from src.core.orm import AssetORM


@pytest.fixture()
async def seeded(asset_session_factory, monkeypatch):
    monkeypatch.setattr(database_mod, "async_session_factory", asset_session_factory)
    asset_id = uuid.uuid4().hex
    async with asset_session_factory() as s:
        s.add(AssetORM(
            id=asset_id, customer_id="t1", name="FGT Funes", ref="fgt60f-funes1",
            asset_type="firewall", type_schema_version=1, status="active",
            managed=True, attributes={}, provenance={}, tags=[],
        ))
        s.add(AssetORM(
            id=uuid.uuid4().hex, customer_id="t1", name="Unmanaged", ref="not-managed",
            asset_type="firewall", type_schema_version=1, status="active",
            managed=False, attributes={}, provenance={}, tags=[],
        ))
        await s.commit()
    return asset_id


async def test_ref_resolves_to_asset_id(seeded):
    assert await _canonicalize_device("fgt60f-funes1", "t1") == seeded


async def test_asset_id_passes_through(seeded):
    assert await _canonicalize_device(seeded, "t1") == seeded


async def test_unknown_value_passes_through(seeded):
    assert await _canonicalize_device("manual-yaml-device", "t1") == "manual-yaml-device"


async def test_tenant_scoped(seeded):
    # t2 has no such ref — the value must not resolve across tenants.
    assert await _canonicalize_device("fgt60f-funes1", "t2") == "fgt60f-funes1"


async def test_unmanaged_asset_not_resolved(seeded):
    assert await _canonicalize_device("not-managed", "t1") == "not-managed"


async def test_non_string_passes_through(seeded):
    assert await _canonicalize_device(None, "t1") is None
    assert await _canonicalize_device(7, "t1") == 7


async def test_db_failure_degrades_to_passthrough(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(database_mod, "async_session_factory", boom)
    assert await _canonicalize_device("fgt60f-funes1", "t1") == "fgt60f-funes1"
