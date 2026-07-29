"""Asset Inventory API endpoints.

Static paths are declared before /{asset_id}. Tenant endpoints use
require_tenant_permission; /assets/global uses require_global_permission
(platform sentinel allowed without a ?customer_id= override).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import (
    get_db,
    get_pagination,
    require_global_permission,
    require_tenant_permission,
)
from src.api.exceptions import APIError
from src.api.schemas.assets import (
    AssetAuditEntry,
    AssetCreate,
    AssetResponse,
    AssetUpdate,
    ImportResponse,
    RelationCreate,
    RelationResponse,
    SyncRunResponse,
)
from src.api.schemas.auth import AuthContext
from src.api.schemas.common import PaginatedResponse, PaginationParams
from src.api.schemas.inventory import GatewaySyncStatus
from src.api.services.gateway_admin_client import GatewayAdminClient
from src.assets import io as assets_io
from src.assets import registry
from src.assets.service import AssetService
from src.assets.validation import sensitive_keys
from src.config import settings

import math

router = APIRouter(prefix="/assets", tags=["assets"])


def _svc(db: AsyncSession) -> AssetService:
    return AssetService(db)


def _actor(auth: AuthContext) -> str:
    if auth.user_id:
        return f"user:{auth.user_id}"
    if auth.key_id:
        return f"api_key:{auth.key_id}"
    return "unknown"


def _asset_out(asset) -> AssetResponse:
    out = AssetResponse.model_validate(asset, from_attributes=True)
    sync = getattr(asset, "gateway_sync_transient", None)
    if sync is not None:
        out.gateway_sync = GatewaySyncStatus(**sync.model_dump())
    return out


def _collect_filters(request: Request, customer_id: Optional[str] = None) -> dict:
    qp = request.query_params
    filters: dict = {
        "q": qp.get("q"),
        "asset_type": qp.get("asset_type"),
        "status": qp.get("status"),
        "criticality": qp.get("criticality"),
        "sync_status": qp.get("sync_status"),
        "owner": qp.get("owner"),
        "tags": qp.getlist("tag"),
        "attrs": {k[5:]: v for k, v in qp.items() if k.startswith("attr.")},
        "customer_id": customer_id,
    }
    managed = qp.get("managed")
    if managed is not None:
        filters["managed"] = managed.lower() in ("true", "1", "yes")
    else:
        filters["managed"] = None
    return filters


async def _paginated_assets(
    svc: AssetService,
    customer_id: Optional[str],
    filters: dict,
    pagination: PaginationParams,
    sort: Optional[str],
    include_deleted: bool,
    can_manage: bool,
) -> PaginatedResponse[AssetResponse]:
    rows, total = await svc.list_assets(
        customer_id, filters,
        page=pagination.page, page_size=pagination.page_size,
        sort=sort, include_deleted=include_deleted,
    )
    if not can_manage:
        await svc.redact_sensitive(rows)
    return PaginatedResponse(
        items=[_asset_out(a) for a in rows],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=math.ceil(total / pagination.page_size) if total else 0,
    )


# --- Static routes (declared before /{asset_id}) ---

@router.get("", response_model=PaginatedResponse[AssetResponse])
async def list_assets(
    request: Request,
    sort: Optional[str] = Query(default=None),
    include_deleted: bool = Query(default=False),
    pagination: PaginationParams = Depends(get_pagination),
    auth: AuthContext = Depends(require_tenant_permission("assets:read")),
    db: AsyncSession = Depends(get_db),
):
    can_manage = auth.has_permission("assets:manage")
    if include_deleted and not can_manage:
        raise APIError(403, "insufficient_permissions",
                       "include_deleted requires assets:manage")
    return await _paginated_assets(
        _svc(db), auth.customer_id, _collect_filters(request),
        pagination, sort, include_deleted, can_manage,
    )


@router.get("/global", response_model=PaginatedResponse[AssetResponse])
async def list_assets_global(
    request: Request,
    tenant: Optional[str] = Query(default=None, description="Filter by tenant"),
    sort: Optional[str] = Query(default=None),
    pagination: PaginationParams = Depends(get_pagination),
    auth: AuthContext = Depends(require_global_permission("assets:read_global")),
    db: AsyncSession = Depends(get_db),
):
    # Cross-tenant aggregate: customer scoping via the explicit `tenant`
    # filter only. Sensitive attributes stay redacted unless assets:manage.
    return await _paginated_assets(
        _svc(db), None, _collect_filters(request, customer_id=tenant),
        pagination, sort, False, auth.has_permission("assets:manage"),
    )


@router.get("/export")
async def export_assets(
    request: Request,
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    sort: Optional[str] = Query(default=None),
    auth: AuthContext = Depends(require_tenant_permission("assets:read")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    rows, total = await svc.list_assets(
        auth.customer_id, _collect_filters(request),
        page=1, page_size=settings.ASSETS_EXPORT_MAX_ROWS, sort=sort,
    )
    if not auth.has_permission("assets:manage"):
        await svc.redact_sensitive(rows)
    headers, data = await assets_io.build_export(db, rows)
    filename = f"assets-{auth.customer_id}"
    if format == "csv":
        return Response(
            content=assets_io.render_csv(headers, data),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )
    return Response(
        content=assets_io.render_xlsx(headers, data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'},
    )


@router.post("/import", response_model=ImportResponse)
async def import_assets(
    request: Request,
    dry_run: bool = Query(default=True),
    match_key: str = Query(default="id"),
    auth: AuthContext = Depends(require_tenant_permission("assets:manage")),
    db: AsyncSession = Depends(get_db),
):
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip()
    body = await request.body()
    if content_type == "text/csv":
        rows = assets_io.parse_csv_rows(body.decode("utf-8-sig"))
    else:
        import json as _json
        try:
            payload = _json.loads(body or b"{}")
        except ValueError:
            raise APIError(422, "validation_error", "Body must be JSON or text/csv")
        rows = payload.get("assets") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise APIError(422, "validation_error",
                           'JSON body must be {"assets": [...]} or a list')
    return await assets_io.import_assets(
        db, auth.customer_id, rows,
        match_key=match_key, dry_run=dry_run, actor=_actor(auth),
    )


@router.get("/types")
async def list_asset_types(
    auth: AuthContext = Depends(require_tenant_permission("assets:read")),
    db: AsyncSession = Depends(get_db),
):
    types = await registry.get_latest_types(db)
    return [t.model_dump(mode="json") for t in types.values()]


@router.get("/types/{type_id}")
async def get_asset_type(
    type_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assets:read")),
    db: AsyncSession = Depends(get_db),
):
    type_def = await registry.get_latest_type(db, type_id)
    if type_def is None:
        raise APIError(404, "not_found", f"Asset type '{type_id}' not found")
    return type_def.model_dump(mode="json")


@router.get("/mcp-packs")
async def list_mcp_packs(
    auth: AuthContext = Depends(require_tenant_permission("assets:manage")),
):
    """Backend passthrough to the gateway pack catalog (/admin/packs)."""
    gateway = GatewayAdminClient.from_settings()
    if gateway is None:
        raise APIError(409, "not_configured", "Gateway admin sync is not configured")
    return await gateway.list_packs()


@router.get("/sync-runs/{run_id}", response_model=SyncRunResponse)
async def get_sync_run(
    run_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assets:read")),
    db: AsyncSession = Depends(get_db),
):
    run = await _svc(db).get_sync_run(auth.customer_id, run_id)
    return SyncRunResponse.model_validate(run, from_attributes=True)


@router.delete("/relations/{relation_id}")
async def delete_relation(
    relation_id: int,
    auth: AuthContext = Depends(require_tenant_permission("assets:write")),
    db: AsyncSession = Depends(get_db),
):
    await _svc(db).delete_relation(auth.customer_id, relation_id, _actor(auth))
    return {"status": "deleted"}


# --- Asset CRUD ---

@router.post("", response_model=AssetResponse, status_code=201)
async def create_asset(
    body: AssetCreate,
    auth: AuthContext = Depends(require_tenant_permission("assets:write")),
    db: AsyncSession = Depends(get_db),
):
    await _check_sensitive_write(db, body.asset_type, body.attributes, auth)
    asset = await _svc(db).create_asset(auth.customer_id, body, _actor(auth))
    return _asset_out(asset)


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: str,
    include_deleted: bool = Query(default=False),
    auth: AuthContext = Depends(require_tenant_permission("assets:read")),
    db: AsyncSession = Depends(get_db),
):
    can_manage = auth.has_permission("assets:manage")
    if include_deleted and not can_manage:
        raise APIError(403, "insufficient_permissions",
                       "include_deleted requires assets:manage")
    svc = _svc(db)
    asset = await svc.get_asset(auth.customer_id, asset_id, include_deleted=include_deleted)
    if not can_manage:
        await svc.redact_sensitive([asset])
    return _asset_out(asset)


@router.patch("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: str,
    body: AssetUpdate,
    auth: AuthContext = Depends(require_tenant_permission("assets:write")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    if body.attributes:
        current = await svc.get_asset(auth.customer_id, asset_id)
        await _check_sensitive_write(
            db, body.asset_type or current.asset_type, body.attributes, auth
        )
    asset = await svc.update_asset(auth.customer_id, asset_id, body, _actor(auth))
    return _asset_out(asset)


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assets:write")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).soft_delete(auth.customer_id, asset_id, _actor(auth))


@router.post("/{asset_id}/restore", response_model=AssetResponse)
async def restore_asset(
    asset_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assets:manage")),
    db: AsyncSession = Depends(get_db),
):
    asset = await _svc(db).restore(auth.customer_id, asset_id, _actor(auth))
    return _asset_out(asset)


# --- Sub-resources ---

@router.get("/{asset_id}/history", response_model=PaginatedResponse[AssetAuditEntry])
async def asset_history(
    asset_id: str,
    pagination: PaginationParams = Depends(get_pagination),
    auth: AuthContext = Depends(require_tenant_permission("assets:read")),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await _svc(db).history(
        auth.customer_id, asset_id,
        page=pagination.page, page_size=pagination.page_size,
    )
    return PaginatedResponse(
        items=[AssetAuditEntry.model_validate(r, from_attributes=True) for r in rows],
        total=total, page=pagination.page, page_size=pagination.page_size,
        total_pages=math.ceil(total / pagination.page_size) if total else 0,
    )


@router.get("/{asset_id}/relations", response_model=List[RelationResponse])
async def list_relations(
    asset_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assets:read")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).list_relations(auth.customer_id, asset_id)


@router.post("/{asset_id}/relations", response_model=RelationResponse, status_code=201)
async def create_relation(
    asset_id: str,
    body: RelationCreate,
    auth: AuthContext = Depends(require_tenant_permission("assets:write")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    rel = await svc.add_relation(auth.customer_id, asset_id, body, _actor(auth))
    rels = await svc.list_relations(auth.customer_id, asset_id)
    return next((r for r in rels if r["id"] == rel.id), rels[-1])


@router.post("/{asset_id}/enrich", status_code=202)
async def enrich_asset(
    asset_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assets:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Queue a deterministic enrichment run (202 + run id)."""
    await _svc(db).get_asset(auth.customer_id, asset_id)  # tenant check -> 404
    from src.assets.enrichment.engine import enqueue_enrichment
    run_id = await enqueue_enrichment(auth.customer_id, asset_id, trigger="manual")
    return {"run_id": run_id, "status": "queued"}


@router.get("/{asset_id}/sync-runs", response_model=PaginatedResponse[SyncRunResponse])
async def list_sync_runs(
    asset_id: str,
    pagination: PaginationParams = Depends(get_pagination),
    auth: AuthContext = Depends(require_tenant_permission("assets:read")),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await _svc(db).list_sync_runs(
        auth.customer_id, asset_id,
        page=pagination.page, page_size=pagination.page_size,
    )
    return PaginatedResponse(
        items=[SyncRunResponse.model_validate(r, from_attributes=True) for r in rows],
        total=total, page=pagination.page, page_size=pagination.page_size,
        total_pages=math.ceil(total / pagination.page_size) if total else 0,
    )


async def _check_sensitive_write(db, asset_type: Optional[str], attributes: dict,
                                 auth: AuthContext) -> None:
    """Sensitive fields require assets:manage to edit."""
    if not attributes or auth.has_permission("assets:manage") or not asset_type:
        return
    type_def = await registry.get_latest_type(db, asset_type)
    if type_def is None:
        return
    hidden = sensitive_keys(type_def) & set(attributes.keys())
    if hidden:
        raise APIError(403, "insufficient_permissions",
                       f"Editing sensitive fields {sorted(hidden)} requires assets:manage")
