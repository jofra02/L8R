"""AssetService tests (in-memory sqlite, stub gateway, no network).

Covers: CRUD + soft delete/restore, tenant isolation (404), attribute
validation against type schemas, provenance stamping, per-asset audit,
relations, and the preserved MCP gateway ordering contract (pending-first,
token never persisted).

Run: uv run pytest src/testing/test_assets_service.py
"""

import json

import pytest

from src.api.exceptions import APIError
from src.api.schemas.assets import AssetCreate, AssetUpdate, RelationCreate
from src.api.schemas.inventory import McpConnection
from src.api.services.gateway_admin_client import GatewaySyncResult
from src.assets.registry import sync_definitions
from src.assets.service import AssetService
from src.core.orm import AssetORM


class StubGatewayClient:
    def __init__(self, result: GatewaySyncResult):
        self.result = result
        self.upserts = []
        self.deletes = []

    async def upsert_device(self, customer_id, payload, *, create):
        self.upserts.append({"customer_id": customer_id, "payload": payload, "create": create})
        return self.result

    async def delete_device(self, customer_id, device_id):
        self.deletes.append({"customer_id": customer_id, "device_id": device_id})
        return self.result


MCP = McpConnection(host="10.0.2.1", port=8443, token="s3cret", primary=True)


@pytest.fixture()
async def session(asset_session_factory):
    async with asset_session_factory() as s:
        await sync_definitions(s)
        yield s


def make_service(session, gateway=None) -> AssetService:
    return AssetService(session, gateway=gateway or StubGatewayClient(
        GatewaySyncResult(status="synced")
    ))


FIREWALL = AssetCreate(
    name="Branch FW", ref="fw_branch", asset_type="firewall",
    manufacturer="Fortinet", criticality="high",
    attributes={"os_version": "7.4.5"},
)


async def test_create_get_update(session):
    svc = make_service(session)
    asset = await svc.create_asset("t1", FIREWALL, "user:u1")
    assert asset.id and asset.ref == "fw_branch"
    assert asset.attributes["os_version"] == "7.4.5"
    assert asset.provenance["attributes.os_version"]["source"] == "manual"
    assert asset.created_by == "user:u1"

    fetched = await svc.get_asset("t1", asset.id)
    assert fetched.name == "Branch FW"

    updated = await svc.update_asset(
        "t1", asset.id, AssetUpdate(location="HQ", attributes={"ha_mode": "standalone"}),
        "user:u2",
    )
    assert updated.location == "HQ"
    assert updated.attributes["ha_mode"] == "standalone"
    assert updated.attributes["os_version"] == "7.4.5"  # merge, not replace
    assert updated.updated_by == "user:u2"


async def test_tenant_isolation_404(session):
    svc = make_service(session)
    asset = await svc.create_asset("t1", FIREWALL, "user:u1")
    with pytest.raises(APIError) as e:
        await svc.get_asset("t2", asset.id)
    assert e.value.status_code == 404


async def test_unknown_type_and_attribute_validation(session):
    svc = make_service(session)
    with pytest.raises(APIError) as e:
        await svc.create_asset("t1", AssetCreate(name="X", asset_type="spaceship"), "u")
    assert e.value.error == "validation_error"

    with pytest.raises(APIError) as e:
        await svc.create_asset("t1", AssetCreate(
            name="FW2", asset_type="firewall",
            attributes={"ha_mode": "quantum"},  # not in enum
        ), "u")
    assert "ha_mode" in e.value.detail

    with pytest.raises(APIError) as e:
        await svc.create_asset("t1", AssetCreate(
            name="FW3", asset_type="firewall",
            attributes={"undeclared_key": 1},  # closed type
        ), "u")
    assert "undeclared_key" in e.value.detail

    # generic is open: any attribute accepted
    ok = await svc.create_asset("t1", AssetCreate(
        name="Thing", asset_type="generic", attributes={"whatever": [1, 2]},
    ), "u")
    assert ok.attributes["whatever"] == [1, 2]


async def test_ref_conflict(session):
    svc = make_service(session)
    await svc.create_asset("t1", FIREWALL, "u")
    with pytest.raises(APIError) as e:
        await svc.create_asset("t1", AssetCreate(
            name="Other", ref="fw_branch", asset_type="generic",
        ), "u")
    assert e.value.error == "conflict"
    # same ref in ANOTHER tenant is fine
    other = await svc.create_asset("t2", AssetCreate(
        name="Other", ref="fw_branch", asset_type="generic",
    ), "u")
    assert other.customer_id == "t2"


async def test_soft_delete_restore_and_audit(session):
    svc = make_service(session)
    asset = await svc.create_asset("t1", FIREWALL, "user:u1")
    out = await svc.soft_delete("t1", asset.id, "user:u1")
    assert out["deleted"] == asset.id

    with pytest.raises(APIError):
        await svc.get_asset("t1", asset.id)  # hidden by default
    deleted = await svc.get_asset("t1", asset.id, include_deleted=True)
    assert deleted.deleted_at is not None

    restored = await svc.restore("t1", asset.id, "user:u1")
    assert restored.deleted_at is None

    rows, total = await svc.history("t1", asset.id, page=1, page_size=50)
    actions = [r.action for r in rows]
    assert "created" in actions and "deleted" in actions and "restored" in actions


async def test_update_diff_audit(session):
    svc = make_service(session)
    asset = await svc.create_asset("t1", FIREWALL, "u")
    await svc.update_asset("t1", asset.id, AssetUpdate(criticality="critical"), "u")
    rows, _ = await svc.history("t1", asset.id, page=1, page_size=50)
    upd = next(r for r in rows if r.action == "updated")
    assert upd.changes["criticality"] == {"old": "high", "new": "critical"}


async def test_relations(session):
    svc = make_service(session)
    fw = await svc.create_asset("t1", FIREWALL, "u")
    sw = await svc.create_asset("t1", AssetCreate(name="Core SW", asset_type="switch"), "u")

    rel = await svc.add_relation("t1", fw.id, RelationCreate(
        target_asset_id=sw.id, relation_type="connected_to",
    ), "u")
    assert rel.source_asset_id == fw.id and rel.target_asset_id == sw.id

    with pytest.raises(APIError) as e:  # duplicate
        await svc.add_relation("t1", fw.id, RelationCreate(
            target_asset_id=sw.id, relation_type="connected_to",
        ), "u")
    assert e.value.error == "conflict"

    with pytest.raises(APIError) as e:  # relation type not allowed for firewall
        await svc.add_relation("t1", fw.id, RelationCreate(
            target_asset_id=sw.id, relation_type="teleports_to",
        ), "u")
    assert e.value.error == "validation_error"

    listed = await svc.list_relations("t1", fw.id)
    assert len(listed) == 1 and listed[0]["target_name"] == "Core SW"

    await svc.delete_relation("t1", listed[0]["id"], "u")
    assert await svc.list_relations("t1", fw.id) == []


async def test_list_filters_and_sort(session):
    svc = make_service(session)
    await svc.create_asset("t1", FIREWALL, "u")
    await svc.create_asset("t1", AssetCreate(
        name="Alpha SW", asset_type="switch", status="maintenance",
    ), "u")

    rows, total = await svc.list_assets("t1", {"asset_type": "switch"}, page=1, page_size=10)
    assert total == 1 and rows[0].asset_type == "switch"

    rows, total = await svc.list_assets("t1", {"q": "branch"}, page=1, page_size=10)
    assert total == 1 and rows[0].ref == "fw_branch"

    rows, _ = await svc.list_assets("t1", {}, page=1, page_size=10, sort="name")
    assert rows[0].name == "Alpha SW"

    with pytest.raises(APIError):
        await svc.list_assets("t1", {}, page=1, page_size=10, sort="evil_column")

    # global (customer_id=None) sees both tenants
    await svc.create_asset("t2", AssetCreate(name="Other FW", asset_type="firewall"), "u")
    rows, total = await svc.list_assets(None, {}, page=1, page_size=10)
    assert total == 3
    rows, total = await svc.list_assets(None, {"customer_id": "t2"}, page=1, page_size=10)
    assert total == 1 and rows[0].customer_id == "t2"


# --- MCP gateway contract (moved from InventoryService) ---

async def test_mcp_create_synced_token_not_persisted(session):
    stub = StubGatewayClient(GatewaySyncResult(status="synced", reloaded=True))
    svc = AssetService(session, gateway=stub)
    asset = await svc.create_asset("t1", AssetCreate(
        name="FW", ref="fw1", asset_type="firewall", mcp_connection=MCP,
    ), "u", auto_enrich=False)

    call = stub.upserts[0]
    assert call["payload"]["connection"]["token"] == "s3cret"
    assert call["payload"]["id"] == asset.id and call["create"] is True

    assert asset.managed and asset.sync_status == "synced"
    assert asset.last_synced_at is not None
    assert "token" not in json.dumps(asset.mcp_config)


async def test_mcp_gateway_error_still_saves(session):
    stub = StubGatewayClient(GatewaySyncResult(status="error", error="connect timeout"))
    svc = AssetService(session, gateway=stub)
    asset = await svc.create_asset("t1", AssetCreate(
        name="FW", ref="fw1", asset_type="firewall", mcp_connection=MCP,
    ), "u", auto_enrich=False)
    assert asset.sync_status == "error" and asset.sync_error == "connect timeout"
    assert (await svc.get_asset("t1", asset.id)).managed


async def test_mcp_local_save_precedes_gateway(session):
    """The gateway must never hold a device the app has no record of."""
    class OrderChecking(StubGatewayClient):
        def __init__(self, session):
            super().__init__(GatewaySyncResult(status="synced"))
            self.session = session
            self.persisted_status = None

        async def upsert_device(self, customer_id, payload, *, create):
            from sqlalchemy import select
            row = (await self.session.execute(
                select(AssetORM).where(AssetORM.id == payload["id"])
            )).scalar_one_or_none()
            self.persisted_status = row.sync_status if row is not None else "MISSING"
            return await super().upsert_device(customer_id, payload, create=create)

    stub = OrderChecking(session)
    svc = AssetService(session, gateway=stub)
    asset = await svc.create_asset("t1", AssetCreate(
        name="FW", ref="fw1", asset_type="firewall", mcp_connection=MCP,
    ), "u", auto_enrich=False)
    assert stub.persisted_status == "pending"
    assert asset.sync_status == "synced"


async def test_mcp_detach_and_delete(session):
    stub = StubGatewayClient(GatewaySyncResult(status="synced"))
    svc = AssetService(session, gateway=stub)
    asset = await svc.create_asset("t1", AssetCreate(
        name="FW", ref="fw1", asset_type="firewall", mcp_connection=MCP,
    ), "u", auto_enrich=False)

    detached = await svc.update_asset("t1", asset.id, AssetUpdate(mcp_managed=False), "u")
    assert stub.deletes == [{"customer_id": "t1", "device_id": asset.id}]
    assert not detached.managed and detached.mcp_config is None

    # re-attach then soft delete -> gateway delete again
    await svc.update_asset("t1", asset.id, AssetUpdate(mcp_connection=MCP), "u",
                           auto_enrich=False)
    await svc.soft_delete("t1", asset.id, "u")
    assert len(stub.deletes) == 2


async def test_mcp_unconfigured_skips(session):
    svc = AssetService(session, gateway=None)
    svc.gateway = None
    asset = await svc.create_asset("t1", AssetCreate(
        name="FW", ref="fw1", asset_type="firewall", mcp_connection=MCP,
    ), "u", auto_enrich=False)
    assert asset.sync_status == "skipped"
