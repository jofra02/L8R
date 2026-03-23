from fastapi import Depends, Header, Query, Request
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_session
from src.api.services.auth_service import AuthService, role_rank
from src.api.services.jwt_service import decode_access_token
from src.api.schemas.auth import AuthContext
from src.api.exceptions import APIError

PLATFORM_SENTINEL = "__platform__"

# Paths exempt from force-password-change blocking
_PASSWORD_CHANGE_EXEMPT_SUFFIXES = {"/auth/change-password", "/auth/me", "/auth/logout"}


async def get_auth_context(
    request: Request,
    authorization: str = Header(..., description="Bearer <token>"),
    customer_id_override: Optional[str] = Query(None, alias="customer_id"),
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    if not authorization.startswith("Bearer "):
        raise APIError(401, "invalid_auth", "Authorization header must be 'Bearer <token>'")

    token = authorization[7:].strip()

    # Route: API key (sk_live_*) vs JWT
    if token.startswith("sk_live_"):
        ctx = await _resolve_api_key_context(token, session)
    else:
        ctx = await _resolve_jwt_context(token, session)

    # Platform admin acting on behalf of a tenant
    if ctx.customer_id == PLATFORM_SENTINEL and customer_id_override:
        ctx = ctx.model_copy(update={"customer_id": customer_id_override})

    # Force password change enforcement (JWT only)
    if ctx.auth_method == "jwt" and getattr(ctx, "_must_change_password", False):
        path = request.url.path.rstrip("/")
        if not any(path.endswith(suffix) for suffix in _PASSWORD_CHANGE_EXEMPT_SUFFIXES):
            raise APIError(403, "password_change_required", "You must change your password before accessing this resource")

    return ctx


async def _resolve_api_key_context(raw_key: str, session: AsyncSession) -> AuthContext:
    service = AuthService(session)
    ctx = await service.validate_key(raw_key)
    if not ctx:
        raise APIError(401, "invalid_key", "API key is invalid, expired, or revoked")
    return ctx


async def _resolve_jwt_context(token: str, session: AsyncSession) -> AuthContext:
    import jwt as pyjwt
    try:
        payload = decode_access_token(token)
    except pyjwt.ExpiredSignatureError:
        raise APIError(401, "token_expired", "Access token has expired")
    except pyjwt.InvalidTokenError:
        raise APIError(401, "invalid_token", "Invalid access token")

    ctx = AuthContext(
        user_id=payload.get("sub"),
        auth_method="jwt",
        customer_id=payload.get("cid", "__none__"),
        permissions=set(payload.get("perms", [])),
        is_platform_admin=payload.get("ipa", False),
    )
    # Carry must-change-password flag for enforcement check above
    if payload.get("mcp"):
        ctx._must_change_password = True  # type: ignore[attr-defined]
    return ctx


def require_permission(*perms: str):
    """Dependency factory: require one or more permissions."""
    async def dependency(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        for p in perms:
            if not auth.has_permission(p):
                raise APIError(
                    403, "insufficient_permissions",
                    f"Requires permission '{p}'. Current permissions: {sorted(auth.permissions)}",
                )
        return auth
    return dependency


# Backward compat — kept so existing endpoints don't break during migration
def require_role(minimum: str):
    min_rank = role_rank(minimum)

    async def dependency(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if role_rank(auth.role) < min_rank:
            raise APIError(
                403, "insufficient_role",
                f"Requires role '{minimum}' or higher. Current: '{auth.role}'",
            )
        return auth

    return dependency
