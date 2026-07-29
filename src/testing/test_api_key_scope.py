"""API key scoping: global (platform) keys vs tenant-bound keys.

Covers the fix for tickets landing on the key's tenant while ?customer_id=
was silently ignored:
- get_auth_context honors ?customer_id= ONLY for platform-scoped contexts
  (tenant-bound keys cannot escape their tenant — isolation preserved)
- POST /auth/keys scope='global' is platform-admin only
- POST /tickets rejects the platform sentinel without an explicit tenant

Run: uv run pytest src/testing/test_api_key_scope.py
"""

from datetime import datetime, timezone

import httpx
import pytest

from src.api.app import create_app
from src.api.dependencies import get_db
from src.api.exceptions import APIError
from src.api.middleware.auth import PLATFORM_SENTINEL, get_auth_context
from src.api.schemas.auth import AuthContext
from src.api.services.auth_service import AuthService, _API_KEY_PERMISSIONS
from src.core.database import get_session


# --- Fakes -----------------------------------------------------------------

class _FakeSession:
    """AsyncSession stand-in for the auth paths (get/add/commit/refresh)."""

    def __init__(self, tenants=None):
        self.tenants = set(tenants or [])
        self.added = []

    async def get(self, model, pk):
        if model.__name__ == "PlatformTenant":
            return object() if pk in self.tenants else None
        return None

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        # Emulate server defaults that a real flush would populate
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if getattr(obj, "is_active", None) is None:
            obj.is_active = True


def _api_key_ctx(customer_id):
    return AuthContext(
        customer_id=customer_id,
        key_id="k1",
        auth_method="api_key",
        permissions=_API_KEY_PERMISSIONS,
        is_platform_admin=False,
    )


def _jwt_ctx(customer_id, is_platform_admin=False, permissions=()):
    return AuthContext(
        user_id="u1",
        auth_method="jwt",
        customer_id=customer_id,
        permissions=set(permissions),
        is_platform_admin=is_platform_admin,
    )


class _FakeRequest:
    class _URL:
        path = "/api/v1/tickets"

    url = _URL()


# --- get_auth_context: override semantics ----------------------------------

async def _resolve(monkeypatch, key_ctx, override, tenants):
    async def fake_validate(self, raw_key):
        return key_ctx

    monkeypatch.setattr(AuthService, "validate_key", fake_validate)
    return await get_auth_context(
        request=_FakeRequest(),
        authorization="Bearer sk_live_x",
        customer_id_override=override,
        session=_FakeSession(tenants=tenants),
    )


async def test_tenant_key_ignores_customer_id_override(monkeypatch):
    """Core isolation invariant: a tenant-bound key cannot escape its tenant."""
    ctx = await _resolve(monkeypatch, _api_key_ctx("acme"), "other-tenant", tenants={"other-tenant"})
    assert ctx.customer_id == "acme"


async def test_global_key_honors_customer_id_override(monkeypatch):
    ctx = await _resolve(monkeypatch, _api_key_ctx(PLATFORM_SENTINEL), "acme", tenants={"acme"})
    assert ctx.customer_id == "acme"


async def test_global_key_unknown_tenant_is_404(monkeypatch):
    with pytest.raises(APIError) as exc:
        await _resolve(monkeypatch, _api_key_ctx(PLATFORM_SENTINEL), "ghost", tenants=set())
    assert exc.value.status_code == 404


async def test_global_key_without_override_keeps_sentinel(monkeypatch):
    ctx = await _resolve(monkeypatch, _api_key_ctx(PLATFORM_SENTINEL), None, tenants=set())
    assert ctx.customer_id == PLATFORM_SENTINEL


# --- /auth/keys endpoint ----------------------------------------------------

@pytest.fixture
def app():
    application = create_app()
    yield application
    application.dependency_overrides.clear()


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _override_db(app, session):
    # /auth routers resolve the session through both aliases
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_session] = lambda: session


async def test_create_global_key_requires_platform_admin(app):
    app.dependency_overrides[get_auth_context] = lambda: _jwt_ctx("acme")
    _override_db(app, _FakeSession())
    async with _client(app) as client:
        resp = await client.post("/api/v1/auth/keys", json={"name": "n8n", "scope": "global"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "platform_admin_required"


async def test_create_global_key_as_platform_admin(app):
    # Platform admin standing inside a tenant (frontend injects ?customer_id=):
    # scope in the body must win and bind the key to the platform sentinel.
    app.dependency_overrides[get_auth_context] = lambda: _jwt_ctx(
        "acme", is_platform_admin=True
    )
    _override_db(app, _FakeSession(tenants={PLATFORM_SENTINEL}))
    async with _client(app) as client:
        resp = await client.post("/api/v1/auth/keys", json={"name": "n8n", "scope": "global"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["scope"] == "global"
    assert body["raw_key"].startswith("sk_live_")


async def test_create_tenant_key_defaults_to_caller_tenant(app):
    app.dependency_overrides[get_auth_context] = lambda: _jwt_ctx("acme")
    _override_db(app, _FakeSession())
    async with _client(app) as client:
        resp = await client.post("/api/v1/auth/keys", json={"name": "webhook"})
    assert resp.status_code == 201
    assert resp.json()["scope"] == "tenant"


async def test_create_tenant_key_from_sentinel_context_is_400(app):
    app.dependency_overrides[get_auth_context] = lambda: _jwt_ctx(
        PLATFORM_SENTINEL, is_platform_admin=True
    )
    _override_db(app, _FakeSession())
    async with _client(app) as client:
        resp = await client.post("/api/v1/auth/keys", json={"name": "webhook"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "tenant_required"


# --- POST /tickets sentinel guard -------------------------------------------

async def test_submit_ticket_rejects_platform_sentinel(app):
    app.dependency_overrides[get_auth_context] = lambda: _api_key_ctx(PLATFORM_SENTINEL)
    _override_db(app, _FakeSession())
    async with _client(app) as client:
        resp = await client.post("/api/v1/tickets", json={"text": "vpn down", "source": "api"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "tenant_required"
