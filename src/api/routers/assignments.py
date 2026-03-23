from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, require_permission
from src.api.schemas.auth import AuthContext
from src.api.services.profile_service import ProfileService
from src.api.exceptions import APIError

router = APIRouter(prefix="/tenants/{customer_id}/users", tags=["assignments"])


class AssignRequest(BaseModel):
    user_id: str
    profile_id: str


class AssignUpdateRequest(BaseModel):
    profile_id: str


class AssignmentResponse(BaseModel):
    id: str
    user_id: str
    customer_id: str
    profile_id: str
    user_email: Optional[str] = None
    user_display_name: Optional[str] = None
    profile_name: Optional[str] = None
    created_at: Optional[datetime] = None


@router.get("", response_model=List[AssignmentResponse])
async def list_tenant_users(
    customer_id: str,
    auth: AuthContext = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    assignments = await service.list_tenant_users(customer_id)
    return [
        AssignmentResponse(
            id=a.id,
            user_id=a.user_id,
            customer_id=a.customer_id,
            profile_id=a.profile_id,
            user_email=a.user.email if a.user else None,
            user_display_name=a.user.display_name if a.user else None,
            profile_name=a.profile.name if a.profile else None,
            created_at=a.created_at,
        )
        for a in assignments
    ]


@router.post("", response_model=AssignmentResponse, status_code=201)
async def assign_user_to_tenant(
    customer_id: str,
    body: AssignRequest,
    auth: AuthContext = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    assignment = await service.assign_user_to_tenant(body.user_id, customer_id, body.profile_id)
    return AssignmentResponse(
        id=assignment.id,
        user_id=assignment.user_id,
        customer_id=assignment.customer_id,
        profile_id=assignment.profile_id,
        created_at=assignment.created_at,
    )


@router.patch("/{user_id}", response_model=AssignmentResponse)
async def update_assignment(
    customer_id: str,
    user_id: str,
    body: AssignUpdateRequest,
    auth: AuthContext = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    assignment = await service.assign_user_to_tenant(user_id, customer_id, body.profile_id)
    return AssignmentResponse(
        id=assignment.id,
        user_id=assignment.user_id,
        customer_id=assignment.customer_id,
        profile_id=assignment.profile_id,
        created_at=assignment.created_at,
    )


@router.delete("/{user_id}", status_code=204)
async def remove_user_from_tenant(
    customer_id: str,
    user_id: str,
    auth: AuthContext = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    removed = await service.remove_user_from_tenant(user_id, customer_id)
    if not removed:
        raise APIError(404, "not_found", "User is not assigned to this tenant")
