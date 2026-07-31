"""Product catalog tests (in-memory sqlite, no network).

Covers: catalog CRUD, case-insensitive uniqueness, rename propagation
across tenants (bulk update + per-asset audit rows), delete-in-use guard,
ensure_product canonicalization on asset create/update, provenance
stamping, list sort/search on product_name, and export/import threading.

Run: uv run pytest src/testing/test_assets_products.py
"""

import pytest
from sqlalchemy import select

from src.api.exceptions import APIError
from src.api.schemas.assets import AssetCreate, AssetUpdate
from src.api.services.gateway_admin_client import GatewaySyncResult
from src.assets import io as assets_io
from src.assets.products import AssetProductService, ensure_product
from src.assets.registry import sync_definitions
from src.assets.service import AssetService
from src.core.orm import AssetAuditLogORM, AssetORM


class StubGatewayClient:
    async def upsert_device(self, customer_id, payload, *, create):
        return GatewaySyncResult(status="synced")

    async def delete_device(self, customer_id, device_id):
        return GatewaySyncResult(status="synced")


@pytest.fixture()
async def session(asset_session_factory):
    async with asset_session_factory() as s:
        await sync_definitions(s)
        yield s


def asset_svc(session) -> AssetService:
    return AssetService(session, gateway=StubGatewayClient())


# --- Catalog CRUD ---

async def test_create_list_ordering(session):
    svc = AssetProductService(session)
    await svc.create_product("Veeam Backup & Replication", "user:u1")
    await svc.create_product("ESXi", "user:u1")
    await svc.create_product("FortiGate", "user:u1")
    names = [p["name"] for p in await svc.list_products()]
    assert names == ["ESXi", "FortiGate", "Veeam Backup & Replication"]
    assert all(p["usage_count"] is None for p in await svc.list_products())


async def test_create_strips_and_rejects_empty(session):
    svc = AssetProductService(session)
    product = await svc.create_product("  Proxmox VE  ", "u")
    assert product.name == "Proxmox VE"
    with pytest.raises(APIError) as e:
        await svc.create_product("   ", "u")
    assert e.value.status_code == 422


async def test_duplicate_case_insensitive_409(session):
    svc = AssetProductService(session)
    await svc.create_product("FortiGate", "u")
    with pytest.raises(APIError) as e:
        await svc.create_product("fortigate", "u")
    assert e.value.status_code == 409


async def test_ensure_product_canonical_casing(session):
    svc = AssetProductService(session)
    await svc.create_product("FortiGate", "u")
    assert await ensure_product(session, "fortigate") == "FortiGate"
    assert await ensure_product(session, "  FORTIGATE ") == "FortiGate"
    with pytest.raises(APIError) as e:
        await ensure_product(session, "Catalyst")
    assert e.value.status_code == 422


# --- Asset threading ---

async def test_asset_create_update_with_product(session):
    products = AssetProductService(session)
    await products.create_product("FortiGate", "u")
    svc = asset_svc(session)

    with pytest.raises(APIError) as e:
        await svc.create_asset("t1", AssetCreate(
            name="FW", asset_type="firewall", product_name="Nonexistent",
        ), "u")
    assert e.value.status_code == 422

    asset = await svc.create_asset("t1", AssetCreate(
        name="FW", asset_type="firewall", product_name="fortigate",
    ), "user:u1")
    assert asset.product_name == "FortiGate"  # canonical casing stored
    assert asset.provenance["product_name"]["source"] == "manual"

    await products.create_product("FortiWiFi", "u")
    updated = await svc.update_asset(
        "t1", asset.id, AssetUpdate(product_name="FORTIWIFI"), "user:u2")
    assert updated.product_name == "FortiWiFi"
    assert updated.provenance["product_name"]["source"] == "manual"

    with pytest.raises(APIError):
        await svc.update_asset("t1", asset.id,
                               AssetUpdate(product_name="Unknown"), "u")


async def test_list_sort_and_search_product_name(session):
    products = AssetProductService(session)
    await products.create_product("FortiGate", "u")
    await products.create_product("ESXi", "u")
    svc = asset_svc(session)
    await svc.create_asset("t1", AssetCreate(
        name="FW", asset_type="firewall", product_name="FortiGate"), "u")
    await svc.create_asset("t1", AssetCreate(
        name="Host", asset_type="server", product_name="ESXi"), "u")

    rows, total = await svc.list_assets("t1", {}, page=1, page_size=10,
                                        sort="product_name")
    assert total == 2 and [r.product_name for r in rows] == ["ESXi", "FortiGate"]

    rows, total = await svc.list_assets("t1", {"q": "fortiga"}, page=1, page_size=10)
    assert total == 1 and rows[0].product_name == "FortiGate"


# --- Rename propagation ---

async def test_rename_propagates_across_tenants_with_audit(session):
    products = AssetProductService(session)
    created = await products.create_product("Catalyst Switch", "u")
    svc = asset_svc(session)
    a1 = await svc.create_asset("t1", AssetCreate(
        name="SW1", asset_type="switch", product_name="Catalyst Switch"), "u")
    a2 = await svc.create_asset("t2", AssetCreate(
        name="SW2", asset_type="switch", product_name="Catalyst Switch"), "u")
    deleted = await svc.create_asset("t1", AssetCreate(
        name="SW3", asset_type="switch", product_name="Catalyst Switch"), "u")
    await svc.soft_delete("t1", deleted.id, "u")

    product, updated = await products.rename_product(
        created.id, "Cisco Catalyst", "user:admin")
    assert product.name == "Cisco Catalyst"
    assert updated == 2  # soft-deleted asset untouched

    names = (await session.execute(
        select(AssetORM.id, AssetORM.product_name)
    )).all()
    by_id = dict(names)
    assert by_id[a1.id] == "Cisco Catalyst"
    assert by_id[a2.id] == "Cisco Catalyst"
    assert by_id[deleted.id] == "Catalyst Switch"

    audits = (await session.execute(
        select(AssetAuditLogORM).where(
            AssetAuditLogORM.actor == "user:admin",
            AssetAuditLogORM.action == "updated",
        )
    )).scalars().all()
    assert {a.asset_id for a in audits} == {a1.id, a2.id}
    assert all(a.changes["product_name"]["new"] == "Cisco Catalyst" for a in audits)


async def test_rename_noop_and_conflict(session):
    products = AssetProductService(session)
    p1 = await products.create_product("ESXi", "u")
    await products.create_product("Proxmox VE", "u")
    product, updated = await products.rename_product(p1.id, "ESXi", "u")
    assert updated == 0
    with pytest.raises(APIError) as e:
        await products.rename_product(p1.id, "proxmox ve", "u")
    assert e.value.status_code == 409


# --- Delete guard ---

async def test_delete_in_use_409_then_ok(session):
    products = AssetProductService(session)
    created = await products.create_product("FortiEDR", "u")
    svc = asset_svc(session)
    asset = await svc.create_asset("t1", AssetCreate(
        name="Console", asset_type="edr_console", product_name="FortiEDR"), "u")

    with pytest.raises(APIError) as e:
        await products.delete_product(created.id)
    assert e.value.status_code == 409

    listed = await products.list_products(include_usage=True)
    assert listed[0]["usage_count"] == 1

    await svc.soft_delete("t1", asset.id, "u")
    await products.delete_product(created.id)  # no live references left
    assert await products.list_products() == []


# --- Export / import ---

async def test_export_includes_product_name(session):
    products = AssetProductService(session)
    await products.create_product("FortiGate", "u")
    svc = asset_svc(session)
    await svc.create_asset("t1", AssetCreate(
        name="FW", asset_type="firewall", product_name="FortiGate"), "u")
    rows, _ = await svc.list_assets("t1", {}, page=1, page_size=10)
    headers, data = await assets_io.build_export(session, rows)
    assert headers.index("product_name") == headers.index("model") + 1
    assert data[0][headers.index("product_name")] == "FortiGate"


async def test_import_validates_product_against_catalog(session):
    products = AssetProductService(session)
    await products.create_product("FortiGate", "u")

    rows = [
        {"name": "FW-A", "asset_type": "firewall", "product_name": "fortigate"},
        {"name": "FW-B", "asset_type": "firewall", "product_name": "Nonexistent"},
    ]
    # Dry-run flags the unknown product without writing anything.
    result = await assets_io.import_assets(
        session, "t1", [dict(r) for r in rows],
        match_key="ref", dry_run=True, actor="u")
    assert result.created == 1 and result.failed == 1
    assert any("product_name" in err for err in result.rows[1].errors)

    result = await assets_io.import_assets(
        session, "t1", [dict(rows[0])],
        match_key="ref", dry_run=False, actor="u")
    assert result.created == 1
    asset = (await session.execute(
        select(AssetORM).where(AssetORM.name == "FW-A")
    )).scalar_one()
    assert asset.product_name == "FortiGate"  # canonicalized on import
