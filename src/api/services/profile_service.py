import uuid
from typing import Optional, List

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.orm import (
    ProfileORM,
    PermissionORM,
    UserTenantProfileORM,
    profile_permissions,
)


class ProfileService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_profiles(self) -> List[ProfileORM]:
        stmt = select(ProfileORM).options(selectinload(ProfileORM.permissions)).order_by(ProfileORM.name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_profile(self, profile_id: str) -> Optional[ProfileORM]:
        stmt = (
            select(ProfileORM)
            .options(selectinload(ProfileORM.permissions))
            .where(ProfileORM.id == profile_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_profile_by_name(self, name: str) -> Optional[ProfileORM]:
        stmt = (
            select(ProfileORM)
            .options(selectinload(ProfileORM.permissions))
            .where(ProfileORM.name == name)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_profile(
        self, name: str, description: str, permission_ids: List[str]
    ) -> ProfileORM:
        profile = ProfileORM(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            is_system=False,
        )
        self.session.add(profile)
        await self.session.flush()

        if permission_ids:
            await self._set_permissions(profile.id, permission_ids)

        await self.session.commit()
        return await self.get_profile(profile.id)

    async def update_profile(
        self, profile_id: str, name: Optional[str] = None,
        description: Optional[str] = None, permission_ids: Optional[List[str]] = None,
    ) -> Optional[ProfileORM]:
        profile = await self.get_profile(profile_id)
        if not profile:
            return None
        if profile.is_system:
            raise ValueError("System profiles cannot be modified")
        if name is not None:
            profile.name = name
        if description is not None:
            profile.description = description
        if permission_ids is not None:
            await self._set_permissions(profile_id, permission_ids)
        await self.session.commit()
        return await self.get_profile(profile_id)

    async def delete_profile(self, profile_id: str) -> bool:
        profile = await self.get_profile(profile_id)
        if not profile:
            return False
        if profile.is_system:
            raise ValueError("System profiles cannot be deleted")
        # Check if in use
        usage_stmt = select(UserTenantProfileORM).where(UserTenantProfileORM.profile_id == profile_id).limit(1)
        usage = await self.session.execute(usage_stmt)
        if usage.scalar_one_or_none():
            raise ValueError("Profile is assigned to users and cannot be deleted")
        await self.session.delete(profile)
        await self.session.commit()
        return True

    async def list_permissions(self) -> List[PermissionORM]:
        stmt = select(PermissionORM).order_by(PermissionORM.resource, PermissionORM.action)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def resolve_permissions_for_profile(self, profile_id: str) -> set[str]:
        profile = await self.get_profile(profile_id)
        if not profile:
            return set()
        return {p.id for p in profile.permissions}

    async def assign_user_to_tenant(
        self, user_id: str, customer_id: str, profile_id: str
    ) -> UserTenantProfileORM:
        # Upsert
        stmt = select(UserTenantProfileORM).where(
            UserTenantProfileORM.user_id == user_id,
            UserTenantProfileORM.customer_id == customer_id,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            existing.profile_id = profile_id
            await self.session.commit()
            return existing
        assignment = UserTenantProfileORM(
            id=str(uuid.uuid4()),
            user_id=user_id,
            customer_id=customer_id,
            profile_id=profile_id,
        )
        self.session.add(assignment)
        await self.session.commit()
        return assignment

    async def remove_user_from_tenant(self, user_id: str, customer_id: str) -> bool:
        stmt = delete(UserTenantProfileORM).where(
            UserTenantProfileORM.user_id == user_id,
            UserTenantProfileORM.customer_id == customer_id,
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def list_tenant_users(self, customer_id: str) -> List[UserTenantProfileORM]:
        stmt = (
            select(UserTenantProfileORM)
            .options(
                selectinload(UserTenantProfileORM.user),
                selectinload(UserTenantProfileORM.profile),
            )
            .where(UserTenantProfileORM.customer_id == customer_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _set_permissions(self, profile_id: str, permission_ids: List[str]) -> None:
        # Clear existing
        await self.session.execute(
            delete(profile_permissions).where(profile_permissions.c.profile_id == profile_id)
        )
        # Insert new
        if permission_ids:
            await self.session.execute(
                profile_permissions.insert(),
                [{"profile_id": profile_id, "permission_id": pid} for pid in permission_ids],
            )
