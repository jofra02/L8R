from fastapi import APIRouter, Depends, Query
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, require_permission
from src.api.schemas.auth import AuthContext
from src.api.schemas.tenants import (
    TenantCreate,
    TenantUpdate,
    TenantListItem,
    TenantCreateResponse,
    TenantDetail,
    EndpointUpsert,
    EndpointResponse,
    ScopeCreate,
    ScopeUpdate,
    ScopeResponse,
    CascadeWarning,
)
from src.api.services.tenant_service import TenantService
from src.api.exceptions import APIError

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _svc(db: AsyncSession) -> TenantService:
    return TenantService(db)


# ---- Tenant CRUD ----


@router.get("", response_model=List[TenantListItem])
async def list_tenants(
    auth: AuthContext = Depends(require_permission("tenants:read")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    return await svc.list_tenants()


@router.post("", response_model=TenantCreateResponse, status_code=201)
async def create_tenant(
    body: TenantCreate,
    auth: AuthContext = Depends(require_permission("tenants:manage")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    tenant, gateway_sync = await svc.create_tenant(
        customer_id=body.customer_id,
        name=body.name,
        plan=body.plan,
    )
    return TenantCreateResponse(
        customer_id=tenant.customer_id,
        name=tenant.name,
        status=tenant.status,
        plan=tenant.plan,
        user_count=0,
        ticket_count=0,
        last_activity=None,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        gateway_sync=gateway_sync.model_dump(),
    )


@router.get("/{customer_id}", response_model=TenantDetail)
async def get_tenant(
    customer_id: str,
    auth: AuthContext = Depends(require_permission("tenants:read")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    detail = await svc.get_tenant_detail(customer_id)
    if not detail:
        raise APIError(404, "not_found", "Tenant not found")
    return detail


@router.patch("/{customer_id}", response_model=TenantListItem)
async def update_tenant(
    customer_id: str,
    body: TenantUpdate,
    auth: AuthContext = Depends(require_permission("tenants:manage")),
    db: AsyncSession = Depends(get_db),
):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise APIError(400, "no_fields", "No fields to update")
    svc = _svc(db)
    tenant = await svc.update_tenant(customer_id, **fields)
    if not tenant:
        raise APIError(404, "not_found", "Tenant not found")
    return TenantListItem.model_validate(tenant)


@router.delete("/{customer_id}", status_code=204)
async def delete_tenant(
    customer_id: str,
    force: bool = Query(False),
    auth: AuthContext = Depends(require_permission("tenants:manage")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    deleted = await svc.delete_tenant(customer_id, force=force)
    if not deleted:
        raise APIError(404, "not_found", "Tenant not found")


@router.post("/{customer_id}/suspend", response_model=TenantListItem)
async def suspend_tenant(
    customer_id: str,
    auth: AuthContext = Depends(require_permission("tenants:manage")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    tenant = await svc.suspend_tenant(customer_id)
    if not tenant:
        raise APIError(404, "not_found", "Tenant not found")
    return TenantListItem.model_validate(tenant)


@router.post("/{customer_id}/activate", response_model=TenantListItem)
async def activate_tenant(
    customer_id: str,
    auth: AuthContext = Depends(require_permission("tenants:manage")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    tenant = await svc.activate_tenant(customer_id)
    if not tenant:
        raise APIError(404, "not_found", "Tenant not found")
    return TenantListItem.model_validate(tenant)


@router.get("/{customer_id}/cascade-warning", response_model=CascadeWarning)
async def get_cascade_warning(
    customer_id: str,
    auth: AuthContext = Depends(require_permission("tenants:manage")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    tenant = await svc.get_tenant(customer_id)
    if not tenant:
        raise APIError(404, "not_found", "Tenant not found")
    counts = await svc.get_cascade_counts(customer_id)
    total = counts["user_count"] + counts["ticket_count"] + counts["api_key_count"]
    return CascadeWarning(
        **counts,
        message=f"Deleting this tenant will remove {total} associated records." if total > 0
        else "No associated data. Safe to delete.",
    )


# ---- Endpoints ----


@router.get("/{customer_id}/endpoints", response_model=Optional[EndpointResponse])
async def get_endpoints(
    customer_id: str,
    auth: AuthContext = Depends(require_permission("tenants:read")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    return await svc.get_endpoints(customer_id)


@router.put("/{customer_id}/endpoints", response_model=EndpointResponse)
async def upsert_endpoints(
    customer_id: str,
    body: EndpointUpsert,
    auth: AuthContext = Depends(require_permission("tenants:manage")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    return await svc.upsert_endpoints(customer_id, body)


# ---- Capability Scopes ----


@router.get("/{customer_id}/scopes", response_model=List[ScopeResponse])
async def list_scopes(
    customer_id: str,
    auth: AuthContext = Depends(require_permission("tenants:read")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    return await svc.list_scopes(customer_id)


@router.post("/{customer_id}/scopes", response_model=ScopeResponse, status_code=201)
async def create_scope(
    customer_id: str,
    body: ScopeCreate,
    auth: AuthContext = Depends(require_permission("tenants:manage")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    return await svc.create_scope(customer_id, body)


@router.patch("/{customer_id}/scopes/{scope_id}", response_model=ScopeResponse)
async def update_scope(
    customer_id: str,
    scope_id: int,
    body: ScopeUpdate,
    auth: AuthContext = Depends(require_permission("tenants:manage")),
    db: AsyncSession = Depends(get_db),
):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise APIError(400, "no_fields", "No fields to update")
    svc = _svc(db)
    scope = await svc.update_scope(scope_id, customer_id, **fields)
    if not scope:
        raise APIError(404, "not_found", "Scope not found")
    return scope


@router.delete("/{customer_id}/scopes/{scope_id}", status_code=204)
async def delete_scope(
    customer_id: str,
    scope_id: int,
    auth: AuthContext = Depends(require_permission("tenants:manage")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    deleted = await svc.delete_scope(scope_id, customer_id)
    if not deleted:
        raise APIError(404, "not_found", "Scope not found")
