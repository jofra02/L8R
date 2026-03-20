from fastapi import Depends, Header, Query
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_session
from src.api.services.auth_service import AuthService, role_rank
from src.api.schemas.auth import AuthContext
from src.api.exceptions import APIError

PLATFORM_SENTINEL = "__platform__"


async def get_auth_context(
    authorization: str = Header(..., description="Bearer sk_live_..."),
    customer_id_override: Optional[str] = Query(None, alias="customer_id"),
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    if not authorization.startswith("Bearer "):
        raise APIError(401, "invalid_auth", "Authorization header must be 'Bearer <key>'")

    raw_key = authorization[7:]
    service = AuthService(session)
    ctx = await service.validate_key(raw_key)
    if not ctx:
        raise APIError(401, "invalid_key", "API key is invalid, expired, or revoked")

    # Platform admin acting on behalf of a tenant
    if ctx.customer_id == PLATFORM_SENTINEL and customer_id_override:
        ctx = AuthContext(
            customer_id=customer_id_override,
            role=ctx.role,
            key_id=ctx.key_id,
        )

    return ctx


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
