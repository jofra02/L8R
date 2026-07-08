"""TenantService <-> MCP gateway tenant lifecycle sync tests (no DB, no network).

Verifies:
1. Create commits locally BEFORE the gateway call and returns the sync result.
2. Gateway error -> tenant still created locally, sync status error.
3. Gateway not configured -> sync status skipped.
4. Delete calls the gateway and proceeds locally even on gateway error.
5. The has_data guard (no force) blocks before any gateway call.
6. GatewayAdminClient: create 409 -> synced (idempotent), delete 404 -> synced,
   delete 409 (manual devices) -> error, network failure -> error.

Run: uv run pytest src/testing/test_tenant_gateway_sync.py
"""

import httpx
import pytest

from src.api.exceptions import APIError
from src.api.services.gateway_admin_client import GatewayAdminClient, GatewaySyncResult
from src.api.services.tenant_service import TenantService
from src.core.orm import PlatformTenant


class FakeSession:
    """Minimal AsyncSession stand-in for the tenant CRUD paths."""

    def __init__(self, existing: dict = None):
        self.rows = dict(existing or {})
        self.events = []

    async def get(self, model, pk):
        return self.rows.get(pk)

    def add(self, obj):
        self.rows[obj.customer_id] = obj
        self.events.append("add")

    async def delete(self, obj):
        self.rows.pop(obj.customer_id, None)
        self.events.append("delete")

    async def commit(self):
        self.events.append("commit")

    async def refresh(self, obj):
        self.events.append("refresh")


class StubGatewayClient:
    """Records tenant calls; returns a configurable result."""

    def __init__(self, result: GatewaySyncResult, events: list = None):
        self.result = result
        self.creates = []
        self.deletes = []
        self.events = events if events is not None else []

    async def create_tenant(self, customer_id, name, description=None):
        self.creates.append({"customer_id": customer_id, "name": name})
        self.events.append("gateway_create")
        return self.result

    async def delete_tenant(self, customer_id):
        self.deletes.append(customer_id)
        self.events.append("gateway_delete")
        return self.result


def make_service(gateway, session=None) -> TenantService:
    svc = TenantService.__new__(TenantService)
    svc.session = session or FakeSession()
    svc.gateway = gateway
    return svc


def make_tenant(cid="t1") -> PlatformTenant:
    return PlatformTenant(customer_id=cid, name="Tenant 1", status="active", plan="standard")


async def _no_data(customer_id):
    return {"user_count": 0, "ticket_count": 0, "api_key_count": 0}


# ---- Service-level ----


async def test_create_commits_before_gateway_and_returns_sync():
    session = FakeSession()
    stub = StubGatewayClient(GatewaySyncResult(status="synced", reloaded=True), session.events)
    svc = make_service(stub, session)

    tenant, sync = await svc.create_tenant("t1", "Tenant 1", "standard")

    assert tenant.customer_id == "t1"
    assert sync.status == "synced"
    assert stub.creates == [{"customer_id": "t1", "name": "Tenant 1"}]
    assert session.events.index("commit") < session.events.index("gateway_create"), (
        "tenant must be committed locally before the gateway call"
    )


async def test_create_gateway_error_still_creates_locally():
    session = FakeSession()
    stub = StubGatewayClient(GatewaySyncResult(status="error", error="connect timeout"))
    svc = make_service(stub, session)

    tenant, sync = await svc.create_tenant("t1", "Tenant 1", "standard")

    assert "t1" in session.rows, "local create must succeed on gateway error"
    assert sync.status == "error" and sync.error == "connect timeout"


async def test_create_unconfigured_gateway_skips():
    svc = make_service(None)
    tenant, sync = await svc.create_tenant("t1", "Tenant 1", "standard")
    assert sync.status == "skipped"


async def test_delete_calls_gateway_and_proceeds_on_error():
    session = FakeSession({"t1": make_tenant()})
    stub = StubGatewayClient(
        GatewaySyncResult(status="error", error="manual devices present"), session.events
    )
    svc = make_service(stub, session)
    svc.get_cascade_counts = _no_data

    deleted = await svc.delete_tenant("t1")

    assert deleted is True
    assert stub.deletes == ["t1"]
    assert "t1" not in session.rows, "local delete must proceed on gateway error"
    assert session.events.index("gateway_delete") < session.events.index("delete"), (
        "gateway cleanup runs before the local delete"
    )


async def test_delete_has_data_guard_blocks_before_gateway():
    session = FakeSession({"t1": make_tenant()})
    stub = StubGatewayClient(GatewaySyncResult(status="synced"))
    svc = make_service(stub, session)

    async def counts(customer_id):
        return {"user_count": 2, "ticket_count": 0, "api_key_count": 0}

    svc.get_cascade_counts = counts

    with pytest.raises(APIError):
        await svc.delete_tenant("t1", force=False)
    assert stub.deletes == [], "gateway must not be called when the guard fires"
    assert "t1" in session.rows


# ---- Client-level (monkeypatched transport) ----


def make_client(responses) -> GatewayAdminClient:
    client = GatewayAdminClient("http://gw:8000", "tok")

    async def fake_request(method, path, json=None):
        outcome = responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        status, body = outcome
        return httpx.Response(status, json=body)

    client._request = fake_request
    return client


async def test_client_create_conflict_is_idempotent():
    client = make_client([(409, {"error": "tenant_exists", "message": "exists"})])
    result = await client.create_tenant("t1", "Tenant 1")
    assert result.status == "synced"


async def test_client_delete_missing_is_idempotent():
    client = make_client([(404, {"error": "unknown_tenant", "message": "missing"})])
    result = await client.delete_tenant("t1")
    assert result.status == "synced"


async def test_client_delete_manual_devices_is_error():
    client = make_client(
        [(409, {"error": "manual_devices_present", "message": "firewalls.yaml present"})]
    )
    result = await client.delete_tenant("t1")
    assert result.status == "error"
    assert "firewalls.yaml" in result.error


async def test_client_network_failure_is_error():
    client = make_client([httpx.ConnectError("boom")])
    result = await client.create_tenant("t1", "Tenant 1")
    assert result.status == "error"
    client = make_client([httpx.ConnectError("boom")])
    result = await client.delete_tenant("t1")
    assert result.status == "error"
