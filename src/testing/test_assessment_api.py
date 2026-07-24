"""Assessment API authorization and tenant scoping (no DB, no lifespan).

Uses httpx ASGITransport (lifespan not executed) with dependency overrides
for auth and DB, mirroring how the routers consume them.

Run: uv run pytest src/testing/test_assessment_api.py
"""

import httpx
import pytest

from src.api.app import create_app
from src.api.dependencies import get_db
from src.api.middleware.auth import get_auth_context
from src.api.schemas.auth import AuthContext


class _FakeResult:
    def __init__(self, value=None, scalars_list=None):
        self._value = value
        self._scalars = scalars_list or []

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def scalars(self):
        outer = self

        class _S:
            def all(self):
                return outer._scalars

        return _S()

    def all(self):
        return self._scalars


class _FakeDB:
    """Queue-driven AsyncSession stand-in: each execute() pops one result."""

    def __init__(self, results):
        self.results = list(results)

    async def execute(self, stmt):
        return self.results.pop(0) if self.results else _FakeResult()

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass

    def add(self, obj):
        pass


def _ctx(permissions, customer_id="acme"):
    return AuthContext(
        user_id="u1", auth_method="jwt", customer_id=customer_id,
        permissions=set(permissions), is_platform_admin=False,
    )


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def app():
    application = create_app()
    yield application
    application.dependency_overrides.clear()


async def test_unauthenticated_request_rejected(app):
    async with _client(app) as client:
        resp = await client.get("/api/v1/assessments")
    assert resp.status_code in (401, 422)  # missing Authorization header


async def test_missing_permission_is_403(app):
    app.dependency_overrides[get_auth_context] = lambda: _ctx({"tickets:read"})
    app.dependency_overrides[get_db] = lambda: _FakeDB([])
    async with _client(app) as client:
        resp = await client.get("/api/v1/assessments")
    assert resp.status_code == 403
    assert resp.json()["error"] == "insufficient_permissions"


async def test_write_permission_required_for_create(app):
    app.dependency_overrides[get_auth_context] = lambda: _ctx({"assessments:read"})
    app.dependency_overrides[get_db] = lambda: _FakeDB([])
    async with _client(app) as client:
        resp = await client.post("/api/v1/assessments", json={
            "name": "x", "definition_id": "d", "definition_version": "1.0.0",
            "component_ids": ["c1"],
        })
    assert resp.status_code == 403


async def test_platform_sentinel_rejected_for_tenant_scoped_route(app):
    app.dependency_overrides[get_auth_context] = lambda: _ctx(
        {"assessments:read"}, customer_id="__platform__"
    )
    app.dependency_overrides[get_db] = lambda: _FakeDB([])
    async with _client(app) as client:
        resp = await client.get("/api/v1/assessments")
    assert resp.status_code == 400
    assert resp.json()["error"] == "tenant_required"


async def test_list_returns_empty_page(app):
    app.dependency_overrides[get_auth_context] = lambda: _ctx({"assessments:read"})
    # list_runs: count query then rows query
    app.dependency_overrides[get_db] = lambda: _FakeDB([
        _FakeResult(value=0),
        _FakeResult(scalars_list=[]),
    ])
    async with _client(app) as client:
        resp = await client.get("/api/v1/assessments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == [] and body["total"] == 0


async def test_cross_tenant_run_is_404(app):
    """The service filters by auth.customer_id; a run of another tenant
    resolves to None -> 404, never 403 (no existence leak)."""
    app.dependency_overrides[get_auth_context] = lambda: _ctx({"assessments:read"})
    app.dependency_overrides[get_db] = lambda: _FakeDB([
        _FakeResult(value=None),  # run lookup misses under this tenant
    ])
    async with _client(app) as client:
        resp = await client.get("/api/v1/assessments/other-tenant-run")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


async def test_unknown_definition_is_404_on_create(app):
    app.dependency_overrides[get_auth_context] = lambda: _ctx({"assessments:write"})
    app.dependency_overrides[get_db] = lambda: _FakeDB([
        _FakeResult(value=None),  # definition version lookup
    ])
    async with _client(app) as client:
        resp = await client.post("/api/v1/assessments", json={
            "name": "x", "definition_id": "ghost", "definition_version": "9.9.9",
            "component_ids": ["c1"],
        })
    assert resp.status_code == 404
