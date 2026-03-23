from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, require_permission
from src.api.schemas.auth import AuthContext
from src.api.services.user_service import UserService
from src.api.exceptions import APIError

router = APIRouter(prefix="/users", tags=["users"])


class UserCreateRequest(BaseModel):
    email: str
    display_name: str
    password: str
    is_platform_admin: bool = False


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    is_active: Optional[bool] = None
    is_platform_admin: Optional[bool] = None


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    is_active: bool
    is_platform_admin: bool
    must_change_password: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.get("", response_model=List[UserResponse])
async def list_users(
    auth: AuthContext = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)
    users = await service.list_users()
    return [UserResponse.model_validate(u) for u in users]


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    body: UserCreateRequest,
    auth: AuthContext = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)
    existing = await service.get_user_by_email(body.email)
    if existing:
        raise APIError(409, "email_exists", f"A user with email '{body.email}' already exists")
    try:
        user = await service.create_user(
            email=body.email,
            display_name=body.display_name,
            password=body.password,
            is_platform_admin=body.is_platform_admin,
            must_change_password=True,
        )
    except ValueError as e:
        raise APIError(400, "password_policy", str(e))
    return UserResponse.model_validate(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    auth: AuthContext = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)
    user = await service.get_user(user_id)
    if not user:
        raise APIError(404, "not_found", "User not found")
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    auth: AuthContext = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise APIError(400, "no_fields", "No fields to update")
    user = await service.update_user(user_id, **fields)
    if not user:
        raise APIError(404, "not_found", "User not found")
    return UserResponse.model_validate(user)


@router.post("/{user_id}/reset-password", status_code=204)
async def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    auth: AuthContext = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)
    try:
        success = await service.admin_reset_password(user_id, body.new_password)
    except ValueError as e:
        raise APIError(400, "password_policy", str(e))
    if not success:
        raise APIError(404, "not_found", "User not found")
