from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_session
from src.api.exceptions import APIError
from src.api.schemas.common import PaginationParams
from src.api.schemas.auth import AuthContext
from src.api.middleware.auth import (  # noqa: re-export
    PLATFORM_SENTINEL,
    get_auth_context,
    require_role,
    require_permission,
)

# Re-export for convenience
__all__ = [
    "get_db",
    "get_pagination",
    "get_auth_context",
    "require_role",
    "require_permission",
    "require_tenant_permission",
    "require_global_permission",
]


async def get_db(session: AsyncSession = Depends(get_session)) -> AsyncSession:
    return session


def get_pagination(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)


def require_tenant_permission(perm: str):
    """Like require_permission, but rejects the platform sentinel as tenant.

    Tenant-scoped modules must not write under '__platform__': it violates
    tenant FKs (500) and can leak orphan devices into the gateway.
    """
    base = require_permission(perm)

    async def dependency(auth: AuthContext = Depends(base)) -> AuthContext:
        if auth.customer_id == PLATFORM_SENTINEL:
            raise APIError(
                400, "tenant_required",
                "Platform admin must target a tenant: pass ?customer_id=<tenant>.",
            )
        return auth

    return dependency


def require_global_permission(perm: str):
    """Permission check for cross-tenant (MSP) endpoints.

    Unlike require_tenant_permission, the '__platform__' sentinel is allowed
    WITHOUT a ?customer_id= override — the endpoint aggregates across
    tenants. v1 scope: platform admins only (the seeded profiles grant the
    *_global permissions to super-admin profiles; delegated multi-tenant
    operators via available_tenants are a documented follow-up).
    """
    return require_permission(perm)
