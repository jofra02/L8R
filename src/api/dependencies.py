from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_session
from src.api.schemas.common import PaginationParams
from src.api.schemas.auth import AuthContext
from src.api.middleware.auth import get_auth_context, require_role, require_permission  # noqa: re-export

# Re-export for convenience
__all__ = [
    "get_db",
    "get_pagination",
    "get_auth_context",
    "require_role",
    "require_permission",
]


async def get_db(session: AsyncSession = Depends(get_session)) -> AsyncSession:
    return session


def get_pagination(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)
