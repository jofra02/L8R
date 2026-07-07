from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, require_permission
from src.api.schemas.auth import AuthContext
from src.api.schemas.inventory import (
    ComponentCreate, ComponentUpdate, ComponentResponse,
    DependencyCreate, DependencyResponse,
    BaselineCreate, BaselineUpdate, BaselineResponse,
    KnownChangeCreate, KnownChangeUpdate, KnownChangeResponse,
    InventoryOverview, FullInventoryResponse, InventoryImport,
)
from src.api.services.inventory_service import InventoryService
from src.api.middleware.auth import PLATFORM_SENTINEL
from src.api.exceptions import APIError

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _svc(db: AsyncSession) -> InventoryService:
    return InventoryService(db)


def require_tenant_permission(perm: str):
    """Like require_permission, but rejects the platform sentinel as tenant.

    Inventory is tenant-scoped: writing under '__platform__' violates the
    client_contexts FK (500) and can leak orphan devices into the gateway.
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


# --- Context-level ---

@router.get("", response_model=InventoryOverview)
async def get_overview(
    auth: AuthContext = Depends(require_tenant_permission("inventory:read")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).get_overview(auth.customer_id)


@router.get("/full", response_model=FullInventoryResponse)
async def get_full_inventory(
    auth: AuthContext = Depends(require_tenant_permission("inventory:read")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).get_full_context(auth.customer_id)


@router.post("/import", response_model=FullInventoryResponse)
async def import_inventory(
    body: InventoryImport,
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).import_context(auth.customer_id, body)


# --- Components ---

@router.get("/components", response_model=list[ComponentResponse])
async def list_components(
    auth: AuthContext = Depends(require_tenant_permission("inventory:read")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).list_components(auth.customer_id)


@router.post("/components", response_model=ComponentResponse, status_code=201)
async def create_component(
    body: ComponentCreate,
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).add_component(auth.customer_id, body)


@router.get("/components/{component_id}", response_model=ComponentResponse)
async def get_component(
    component_id: str,
    auth: AuthContext = Depends(require_tenant_permission("inventory:read")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).get_component(auth.customer_id, component_id)


@router.patch("/components/{component_id}", response_model=ComponentResponse)
async def update_component(
    component_id: str,
    body: ComponentUpdate,
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).update_component(auth.customer_id, component_id, body)


@router.delete("/components/{component_id}")
async def delete_component(
    component_id: str,
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).delete_component(auth.customer_id, component_id)


# --- Dependencies ---

@router.get("/dependencies", response_model=list[DependencyResponse])
async def list_dependencies(
    auth: AuthContext = Depends(require_tenant_permission("inventory:read")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).list_dependencies(auth.customer_id)


@router.post("/dependencies", response_model=DependencyResponse, status_code=201)
async def create_dependency(
    body: DependencyCreate,
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).add_dependency(auth.customer_id, body)


@router.delete("/dependencies")
async def delete_dependency(
    source_id: str = Query(...),
    target_id: str = Query(...),
    relation: str = Query(...),
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    await _svc(db).delete_dependency(auth.customer_id, source_id, target_id, relation)
    return {"status": "deleted"}


# --- Baselines ---

@router.get("/baselines", response_model=list[BaselineResponse])
async def list_baselines(
    auth: AuthContext = Depends(require_tenant_permission("inventory:read")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).list_baselines(auth.customer_id)


@router.post("/baselines", response_model=BaselineResponse, status_code=201)
async def create_baseline(
    body: BaselineCreate,
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).add_baseline(auth.customer_id, body)


@router.patch("/baselines/{component_id}/{metric}", response_model=BaselineResponse)
async def update_baseline(
    component_id: str,
    metric: str,
    body: BaselineUpdate,
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).update_baseline(auth.customer_id, component_id, metric, body)


@router.delete("/baselines/{component_id}/{metric}")
async def delete_baseline(
    component_id: str,
    metric: str,
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    await _svc(db).delete_baseline(auth.customer_id, component_id, metric)
    return {"status": "deleted"}


# --- Known Changes ---

@router.get("/changes", response_model=list[KnownChangeResponse])
async def list_known_changes(
    auth: AuthContext = Depends(require_tenant_permission("inventory:read")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).list_known_changes(auth.customer_id)


@router.post("/changes", response_model=KnownChangeResponse, status_code=201)
async def create_known_change(
    body: KnownChangeCreate,
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).add_known_change(auth.customer_id, body)


@router.patch("/changes/{index}", response_model=KnownChangeResponse)
async def update_known_change(
    index: int,
    body: KnownChangeUpdate,
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    return await _svc(db).update_known_change(auth.customer_id, index, body)


@router.delete("/changes/{index}")
async def delete_known_change(
    index: int,
    auth: AuthContext = Depends(require_tenant_permission("inventory:write")),
    db: AsyncSession = Depends(get_db),
):
    await _svc(db).delete_known_change(auth.customer_id, index)
    return {"status": "deleted"}
