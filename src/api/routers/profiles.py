from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, require_permission
from src.api.schemas.auth import AuthContext
from src.api.services.profile_service import ProfileService
from src.api.exceptions import APIError

router = APIRouter(prefix="/profiles", tags=["profiles"])


class PermissionResponse(BaseModel):
    id: str
    resource: str
    action: str
    description: str

    model_config = {"from_attributes": True}


class ProfileResponse(BaseModel):
    id: str
    name: str
    description: str
    is_system: bool
    permissions: List[PermissionResponse] = []
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProfileCreateRequest(BaseModel):
    name: str
    description: str = ""
    permission_ids: List[str] = []


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission_ids: Optional[List[str]] = None


@router.get("", response_model=List[ProfileResponse])
async def list_profiles(
    auth: AuthContext = Depends(require_permission("profiles:read")),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    profiles = await service.list_profiles()
    return [ProfileResponse.model_validate(p) for p in profiles]


@router.post("", response_model=ProfileResponse, status_code=201)
async def create_profile(
    body: ProfileCreateRequest,
    auth: AuthContext = Depends(require_permission("profiles:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    existing = await service.get_profile_by_name(body.name)
    if existing:
        raise APIError(409, "name_exists", f"A profile named '{body.name}' already exists")
    profile = await service.create_profile(body.name, body.description, body.permission_ids)
    return ProfileResponse.model_validate(profile)


@router.get("/permissions", response_model=List[PermissionResponse])
async def list_permissions(
    auth: AuthContext = Depends(require_permission("profiles:read")),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    perms = await service.list_permissions()
    return [PermissionResponse.model_validate(p) for p in perms]


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(
    profile_id: str,
    auth: AuthContext = Depends(require_permission("profiles:read")),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    profile = await service.get_profile(profile_id)
    if not profile:
        raise APIError(404, "not_found", "Profile not found")
    return ProfileResponse.model_validate(profile)


@router.patch("/{profile_id}", response_model=ProfileResponse)
async def update_profile(
    profile_id: str,
    body: ProfileUpdateRequest,
    auth: AuthContext = Depends(require_permission("profiles:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    try:
        profile = await service.update_profile(
            profile_id,
            name=body.name,
            description=body.description,
            permission_ids=body.permission_ids,
        )
    except ValueError as e:
        raise APIError(400, "invalid_operation", str(e))
    if not profile:
        raise APIError(404, "not_found", "Profile not found")
    return ProfileResponse.model_validate(profile)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    auth: AuthContext = Depends(require_permission("profiles:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    try:
        deleted = await service.delete_profile(profile_id)
    except ValueError as e:
        raise APIError(400, "invalid_operation", str(e))
    if not deleted:
        raise APIError(404, "not_found", "Profile not found")
