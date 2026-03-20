from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, require_role
from src.api.schemas.auth import ApiKeyCreate, ApiKeyResponse, ApiKeyCreatedResponse, AuthContext
from src.api.services.auth_service import AuthService, role_rank
from src.api.exceptions import APIError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=AuthContext)
async def get_me(
    auth: AuthContext = Depends(require_role("viewer")),
):
    """Return the authenticated caller's context (customer_id, role, key_id)."""
    return auth


@router.post("/keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_key(
    body: ApiKeyCreate,
    auth: AuthContext = Depends(require_role("tenant_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Issue a new API key. The raw key is returned only once."""
    # Cannot create keys with a higher role than your own
    if role_rank(body.role) > role_rank(auth.role):
        raise APIError(403, "role_escalation", "Cannot create a key with a higher role than your own")

    service = AuthService(db)
    raw_key, key_orm = await service.create_key(
        customer_id=auth.customer_id,
        name=body.name,
        role=body.role,
        created_by=auth.key_id,
        expires_at=body.expires_at,
    )
    return ApiKeyCreatedResponse(
        id=key_orm.id,
        key_prefix=key_orm.key_prefix,
        name=key_orm.name,
        role=key_orm.role,
        is_active=key_orm.is_active,
        expires_at=key_orm.expires_at,
        last_used_at=key_orm.last_used_at,
        created_at=key_orm.created_at,
        raw_key=raw_key,
    )


@router.get("/keys", response_model=list[ApiKeyResponse])
async def list_keys(
    auth: AuthContext = Depends(require_role("tenant_admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all API keys for the authenticated tenant."""
    service = AuthService(db)
    keys = await service.list_keys(auth.customer_id)
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.delete("/keys/{key_id}", status_code=204)
async def revoke_key(
    key_id: str,
    auth: AuthContext = Depends(require_role("tenant_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API key."""
    service = AuthService(db)
    revoked = await service.revoke_key(key_id, auth.customer_id)
    if not revoked:
        raise APIError(404, "not_found", "Key not found or already revoked")


@router.post("/keys/{key_id}/rotate", response_model=ApiKeyCreatedResponse)
async def rotate_key(
    key_id: str,
    auth: AuthContext = Depends(require_role("tenant_admin")),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an existing key and issue a new one with the same metadata."""
    service = AuthService(db)
    result = await service.rotate_key(key_id, auth.customer_id)
    if not result:
        raise APIError(404, "not_found", "Key not found, already revoked, or not owned by tenant")
    raw_key, key_orm = result
    return ApiKeyCreatedResponse(
        id=key_orm.id,
        key_prefix=key_orm.key_prefix,
        name=key_orm.name,
        role=key_orm.role,
        is_active=key_orm.is_active,
        expires_at=key_orm.expires_at,
        last_used_at=key_orm.last_used_at,
        created_at=key_orm.created_at,
        raw_key=raw_key,
    )
