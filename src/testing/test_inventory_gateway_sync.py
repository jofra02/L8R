"""InventoryService <-> MCP gateway sync tests (no DB, no network).

Verifies:
1. Create with mcp_connection -> gateway receives the payload (token included),
   persisted metadata carries the mcp block WITHOUT the token, sync status synced.
2. Gateway error -> local save still succeeds, sync status error.
3. Update with mcp_managed=False -> gateway delete called, mcp metadata stripped.
4. Delete of a managed component -> gateway delete called.
5. Gateway not configured -> sync status skipped, local save succeeds.
6. Local persistence happens BEFORE the gateway sync (no orphan devices).

Run: uv run pytest src/testing/test_inventory_gateway_sync.py
"""

import json
from typing import Optional

from src.core.models import ClientContext
from src.api.schemas.inventory import ComponentCreate, ComponentUpdate, McpConnection
from src.api.services.gateway_admin_client import GatewaySyncResult
from src.api.services.inventory_service import InventoryService


class FakeContextStore:
    """In-memory ContextStore replacement."""

    def __init__(self):
        self.contexts = {}

    async def get_active_context(self, customer_id: str) -> Optional[ClientContext]:
        raw = self.contexts.get(customer_id)
        return ClientContext(**raw) if raw else None

    async def save_context(self, context: ClientContext) -> None:
        self.contexts[context.customer_id] = context.model_dump()


class StubGatewayClient:
    """Records calls; returns a configurable result."""

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


def make_service(gateway) -> InventoryService:
    svc = InventoryService.__new__(InventoryService)
    svc.store = FakeContextStore()
    svc.gateway = gateway
    return svc


MCP = McpConnection(host="10.0.2.1", port=8443, token="s3cret", primary=True)
CREATE = ComponentCreate(
    id="fw_branch", ref="Branch FW", role="firewall", vendor="fortinet", mcp_connection=MCP
)


async def test_create_synced():
    stub = StubGatewayClient(GatewaySyncResult(status="synced", reloaded=True))
    svc = make_service(stub)
    out = await svc.add_component("t1", CREATE)

    assert len(stub.upserts) == 1, "gateway upsert not called"
    call = stub.upserts[0]
    assert call["customer_id"] == "t1" and call["create"] is True
    assert call["payload"]["id"] == "fw_branch"
    assert call["payload"]["type"] == "fortios"
    assert call["payload"]["connection"]["token"] == "s3cret"

    assert out["gateway_sync"]["status"] == "synced"
    persisted = json.dumps((await svc.store.get_active_context("t1")).model_dump())
    assert "s3cret" not in persisted, "token leaked into persisted context"
    mcp_meta = out["metadata"]["mcp"]
    assert mcp_meta["managed"] is True and mcp_meta["sync"]["status"] == "synced"
    assert "token" not in mcp_meta


async def test_create_gateway_error_still_saves():
    stub = StubGatewayClient(GatewaySyncResult(status="error", error="connect timeout"))
    svc = make_service(stub)
    out = await svc.add_component("t1", CREATE)

    ctx = await svc.store.get_active_context("t1")
    assert len(ctx.inventory) == 1, "local save must succeed on gateway error"
    assert out["gateway_sync"]["status"] == "error"
    assert out["metadata"]["mcp"]["sync"]["last_error"] == "connect timeout"


async def test_detach_deletes_in_gateway():
    stub = StubGatewayClient(GatewaySyncResult(status="synced"))
    svc = make_service(stub)
    await svc.add_component("t1", CREATE)

    out = await svc.update_component("t1", "fw_branch", ComponentUpdate(mcp_managed=False))
    assert stub.deletes == [{"customer_id": "t1", "device_id": "fw_branch"}]
    assert "mcp" not in out["metadata"], "mcp metadata must be stripped on detach"


async def test_delete_managed_component():
    stub = StubGatewayClient(GatewaySyncResult(status="synced"))
    svc = make_service(stub)
    await svc.add_component("t1", CREATE)

    out = await svc.delete_component("t1", "fw_branch")
    assert stub.deletes == [{"customer_id": "t1", "device_id": "fw_branch"}]
    assert out["gateway_sync"]["status"] == "synced"
    ctx = await svc.store.get_active_context("t1")
    assert ctx.inventory == []


async def test_unconfigured_gateway_skips():
    svc = make_service(None)
    out = await svc.add_component("t1", CREATE)
    assert out["gateway_sync"]["status"] == "skipped"
    ctx = await svc.store.get_active_context("t1")
    assert len(ctx.inventory) == 1


async def test_local_save_precedes_gateway_sync():
    """The gateway must never hold a device the app has no record of."""

    class OrderCheckingGateway(StubGatewayClient):
        def __init__(self, store):
            super().__init__(GatewaySyncResult(status="synced"))
            self.store = store
            self.persisted_sync_status = None

        async def upsert_device(self, customer_id, payload, *, create):
            ctx = await self.store.get_active_context(customer_id)
            component = next(
                (c for c in (ctx.inventory if ctx else []) if c.id == payload["id"]), None
            )
            if component is not None:
                self.persisted_sync_status = component.metadata["mcp"]["sync"]["status"]
            return await super().upsert_device(customer_id, payload, create=create)

    svc = make_service(None)
    gateway = OrderCheckingGateway(svc.store)
    svc.gateway = gateway

    out = await svc.add_component("t1", CREATE)
    assert gateway.persisted_sync_status == "pending", (
        "component must be persisted locally (sync pending) before the gateway call"
    )
    assert out["metadata"]["mcp"]["sync"]["status"] == "synced"
