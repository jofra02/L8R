"""Legacy /inventory shim <-> MCP gateway sync tests (sqlite, no network).

The component CRUD now delegates to AssetService (relational assets), but
the legacy response shapes and the gateway contract are preserved:
1. Create with mcp_connection -> gateway receives the payload (token included),
   the response carries the mcp block WITHOUT the token, sync status synced.
2. Gateway error -> local save still succeeds, sync status error.
3. Update with mcp_managed=False -> gateway delete called, mcp block stripped.
4. Delete of a managed component -> gateway delete called.
5. Gateway not configured -> sync status skipped, local save succeeds.
6. Local persistence happens BEFORE the gateway sync (no orphan devices).

Run: uv run pytest src/testing/test_inventory_gateway_sync.py
"""

import json

import pytest
from sqlalchemy import select

from src.api.schemas.inventory import ComponentCreate, ComponentUpdate, McpConnection
from src.api.services.gateway_admin_client import GatewaySyncResult
from src.api.services.inventory_service import InventoryService
from src.assets.registry import sync_definitions
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
CREATE = ComponentCreate(
    id="fw_branch", ref="Branch FW", role="firewall", vendor="fortinet",
    mcp_connection=MCP,
)


@pytest.fixture()
async def session(asset_session_factory):
    async with asset_session_factory() as s:
        await sync_definitions(s)
        yield s


def make_service(session, gateway) -> InventoryService:
    svc = InventoryService(session, gateway=gateway or GatewaySyncResult(status="skipped"))
    if gateway is None:
        svc.gateway = None
        svc.assets.gateway = None
    return svc


async def test_create_synced(session):
    stub = StubGatewayClient(GatewaySyncResult(status="synced", reloaded=True))
    svc = InventoryService(session, gateway=stub)
    out = await svc.add_component("t1", CREATE)

    assert len(stub.upserts) == 1, "gateway upsert not called"
    call = stub.upserts[0]
    assert call["customer_id"] == "t1" and call["create"] is True
    assert call["payload"]["id"] == "fw_branch"
    assert call["payload"]["type"] == "fortios"
    assert call["payload"]["connection"]["token"] == "s3cret"

    assert out["gateway_sync"]["status"] == "synced"
    # legacy Component shape preserved
    assert out["id"] == "fw_branch" and out["ref"] == "Branch FW"
    assert out["role"] == "firewall" and out["vendor"] == "fortinet"
    mcp_meta = out["metadata"]["mcp"]
    assert mcp_meta["managed"] is True and mcp_meta["sync"]["status"] == "synced"
    assert "token" not in mcp_meta

    # token never persisted anywhere in the asset row
    row = (await session.execute(
        select(AssetORM).where(AssetORM.id == "fw_branch"))).scalar_one()
    assert "s3cret" not in json.dumps(row.mcp_config)


async def test_create_gateway_error_still_saves(session):
    stub = StubGatewayClient(GatewaySyncResult(status="error", error="connect timeout"))
    svc = InventoryService(session, gateway=stub)
    out = await svc.add_component("t1", CREATE)

    assert len(await svc.list_components("t1")) == 1, "local save must succeed on gateway error"
    assert out["gateway_sync"]["status"] == "error"
    assert out["metadata"]["mcp"]["sync"]["last_error"] == "connect timeout"


async def test_detach_deletes_in_gateway(session):
    stub = StubGatewayClient(GatewaySyncResult(status="synced"))
    svc = InventoryService(session, gateway=stub)
    await svc.add_component("t1", CREATE)

    out = await svc.update_component("t1", "fw_branch", ComponentUpdate(mcp_managed=False))
    assert stub.deletes == [{"customer_id": "t1", "device_id": "fw_branch"}]
    assert "mcp" not in out["metadata"], "mcp metadata must be stripped on detach"


async def test_delete_managed_component(session):
    stub = StubGatewayClient(GatewaySyncResult(status="synced"))
    svc = InventoryService(session, gateway=stub)
    await svc.add_component("t1", CREATE)

    out = await svc.delete_component("t1", "fw_branch")
    assert stub.deletes == [{"customer_id": "t1", "device_id": "fw_branch"}]
    assert out["gateway_sync"]["status"] == "synced"
    assert await svc.list_components("t1") == []


async def test_unconfigured_gateway_skips(session):
    svc = make_service(session, None)
    out = await svc.add_component("t1", CREATE)
    assert out["gateway_sync"]["status"] == "skipped"
    assert len(await svc.list_components("t1")) == 1


async def test_local_save_precedes_gateway_sync(session):
    """The gateway must never hold a device the app has no record of."""

    class OrderCheckingGateway(StubGatewayClient):
        def __init__(self, session):
            super().__init__(GatewaySyncResult(status="synced"))
            self.session = session
            self.persisted_sync_status = None

        async def upsert_device(self, customer_id, payload, *, create):
            row = (await self.session.execute(
                select(AssetORM).where(AssetORM.id == payload["id"])
            )).scalar_one_or_none()
            self.persisted_sync_status = row.sync_status if row is not None else "MISSING"
            return await super().upsert_device(customer_id, payload, create=create)

    gateway = OrderCheckingGateway(session)
    svc = InventoryService(session, gateway=gateway)

    out = await svc.add_component("t1", CREATE)
    assert gateway.persisted_sync_status == "pending", (
        "component must be persisted locally (sync pending) before the gateway call"
    )
    assert out["metadata"]["mcp"]["sync"]["status"] == "synced"


async def test_legacy_metadata_replace_semantics(session):
    """ComponentUpdate.metadata is a full replace (merge + explicit deletes)."""
    stub = StubGatewayClient(GatewaySyncResult(status="synced"))
    svc = InventoryService(session, gateway=stub)
    await svc.add_component("t1", ComponentCreate(
        id="srv1", ref="Server", role="server",
        metadata={"os": "linux", "rack": "R1"},
    ))
    out = await svc.update_component("t1", "srv1", ComponentUpdate(
        metadata={"os": "windows"},
    ))
    assert out["metadata"] == {"os": "windows"}, "old keys must be dropped on replace"
