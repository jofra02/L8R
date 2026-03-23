from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, require_role, require_permission, get_auth_context
from src.api.schemas.auth import (
    ApiKeyCreate, ApiKeyResponse, ApiKeyCreatedResponse, AuthContext,
    LoginRequest, TokenResponse, RefreshRequest, ChangePasswordRequest, SwitchTenantRequest,
)
from src.api.services.auth_service import AuthService, role_rank
from src.api.services.user_service import UserService
from src.api.services.jwt_service import create_access_token
from src.api.exceptions import APIError

router = APIRouter(prefix="/auth", tags=["auth"])


# --- JWT Auth Endpoints ---

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with email + password. Returns JWT tokens."""
    service = UserService(db)
    result = await service.authenticate(body.email, body.password, body.customer_id)
    if not result:
        raise APIError(401, "invalid_credentials", "Invalid email or password")
    return TokenResponse(**result)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for a new access token."""
    service = UserService(db)
    result = await service.refresh_access_token(body.refresh_token)
    if not result:
        raise APIError(401, "invalid_refresh_token", "Refresh token is invalid, expired, or revoked")
    return TokenResponse(**result)


@router.post("/logout", status_code=204)
async def logout(
    body: RefreshRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a refresh token."""
    service = UserService(db)
    await service.revoke_refresh_token(body.refresh_token)


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Change the authenticated user's password."""
    if not auth.user_id:
        raise APIError(400, "api_key_auth", "Password change is only available for JWT-authenticated users")
    service = UserService(db)
    try:
        success = await service.change_password(auth.user_id, body.current_password, body.new_password)
    except ValueError as e:
        raise APIError(400, "password_policy", str(e))
    if not success:
        raise APIError(400, "invalid_password", "Current password is incorrect")


@router.post("/switch-tenant", response_model=TokenResponse)
async def switch_tenant(
    body: SwitchTenantRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Issue a new access token scoped to a different tenant."""
    if not auth.user_id:
        raise APIError(400, "api_key_auth", "Tenant switching is only available for JWT-authenticated users")
    # Re-authenticate to resolve permissions for the new tenant
    service = UserService(db)
    user = await service.get_user(auth.user_id)
    if not user:
        raise APIError(404, "user_not_found", "User not found")

    # Check tenant access
    if not user.is_platform_admin:
        from sqlalchemy import select
        from src.core.orm import UserTenantProfileORM, ProfileORM
        from sqlalchemy.orm import selectinload
        tp_stmt = (
            select(UserTenantProfileORM)
            .options(selectinload(UserTenantProfileORM.profile).selectinload(ProfileORM.permissions))
            .where(
                UserTenantProfileORM.user_id == auth.user_id,
                UserTenantProfileORM.customer_id == body.customer_id,
            )
        )
        tp_result = await db.execute(tp_stmt)
        tp = tp_result.scalar_one_or_none()
        if not tp:
            raise APIError(403, "no_tenant_access", f"User has no access to tenant '{body.customer_id}'")
        permissions = [p.id for p in tp.profile.permissions]
    else:
        from sqlalchemy import select
        from src.core.orm import PermissionORM
        perm_result = await db.execute(select(PermissionORM.id))
        permissions = list(perm_result.scalars().all())

    access_token = create_access_token(
        user_id=auth.user_id,
        customer_id="__platform__" if user.is_platform_admin else body.customer_id,
        permissions=permissions,
        is_platform_admin=user.is_platform_admin,
        must_change_password=user.must_change_password,
    )
    from src.config import settings
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me")
async def get_me(
    auth: AuthContext = Depends(get_auth_context),
):
    """Return the authenticated caller's context."""
    return auth


@router.post("/keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_key(
    body: ApiKeyCreate,
    auth: AuthContext = Depends(require_permission("keys:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Issue a new API key. The raw key is returned only once."""
    service = AuthService(db)
    raw_key, key_orm = await service.create_key(
        customer_id=auth.customer_id,
        name=body.name,
        role=body.role,
        created_by=auth.key_id,
        expires_at=body.expires_at,
        profile_id=body.profile_id,
        created_by_user_id=auth.user_id,
    )
    return ApiKeyCreatedResponse(
        id=key_orm.id,
        key_prefix=key_orm.key_prefix,
        name=key_orm.name,
        role=key_orm.role,
        profile_id=key_orm.profile_id,
        is_active=key_orm.is_active,
        expires_at=key_orm.expires_at,
        last_used_at=key_orm.last_used_at,
        created_at=key_orm.created_at,
        raw_key=raw_key,
    )


@router.get("/keys", response_model=list[ApiKeyResponse])
async def list_keys(
    auth: AuthContext = Depends(require_permission("keys:read")),
    db: AsyncSession = Depends(get_db),
):
    """List all API keys for the authenticated tenant."""
    service = AuthService(db)
    keys = await service.list_keys(auth.customer_id)
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.delete("/keys/{key_id}", status_code=204)
async def revoke_key(
    key_id: str,
    auth: AuthContext = Depends(require_permission("keys:manage")),
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
    auth: AuthContext = Depends(require_permission("keys:manage")),
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
        profile_id=key_orm.profile_id,
        is_active=key_orm.is_active,
        expires_at=key_orm.expires_at,
        last_used_at=key_orm.last_used_at,
        created_at=key_orm.created_at,
        raw_key=raw_key,
    )
