import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.orm import ApiKeyORM, ProfileORM, PermissionORM
from src.api.schemas.auth import AuthContext


ROLE_HIERARCHY = ["viewer", "operator", "tenant_admin", "platform_admin"]

# Legacy role → system profile name mapping (for API keys without profile_id)
_LEGACY_ROLE_PROFILE_MAP = {
    "viewer": "Super Admin Readonly",
    "operator": "Tenant Admin",
    "tenant_admin": "Tenant Admin",
    "platform_admin": "Super Admin",
}


def _generate_raw_key() -> str:
    return f"sk_live_{secrets.token_hex(32)}"


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _prefix(raw_key: str) -> str:
    return raw_key[:12]


def role_rank(role: str) -> int:
    try:
        return ROLE_HIERARCHY.index(role)
    except ValueError:
        return -1


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_key(
        self,
        customer_id: str,
        name: str,
        role: str,
        created_by: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        profile_id: Optional[str] = None,
        created_by_user_id: Optional[str] = None,
    ) -> Tuple[str, ApiKeyORM]:
        raw_key = _generate_raw_key()
        key_orm = ApiKeyORM(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            key_hash=_hash_key(raw_key),
            key_prefix=_prefix(raw_key),
            name=name,
            role=role,
            created_by=created_by,
            expires_at=expires_at,
            profile_id=profile_id,
            created_by_user_id=created_by_user_id,
        )
        self.session.add(key_orm)
        await self.session.commit()
        await self.session.refresh(key_orm)
        return raw_key, key_orm

    async def validate_key(self, raw_key: str) -> Optional[AuthContext]:
        key_hash = _hash_key(raw_key)
        stmt = select(ApiKeyORM).where(
            ApiKeyORM.key_hash == key_hash,
            ApiKeyORM.is_active == True,
        )
        result = await self.session.execute(stmt)
        key = result.scalar_one_or_none()
        if not key:
            return None
        if key.expires_at and key.expires_at < datetime.now(timezone.utc):
            return None
        # Touch last_used_at
        await self.session.execute(
            update(ApiKeyORM)
            .where(ApiKeyORM.id == key.id)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await self.session.commit()

        # Resolve permissions
        permissions = await self._resolve_api_key_permissions(key)

        return AuthContext(
            customer_id=key.customer_id,
            role=key.role,
            key_id=key.id,
            auth_method="api_key",
            permissions=permissions,
            is_platform_admin=(key.role == "platform_admin"),
        )

    async def _resolve_api_key_permissions(self, key: ApiKeyORM) -> set[str]:
        """Resolve permissions for an API key (profile-based or legacy role mapping)."""
        if key.profile_id:
            # New path: resolve from assigned profile
            stmt = (
                select(ProfileORM)
                .options(selectinload(ProfileORM.permissions))
                .where(ProfileORM.id == key.profile_id)
            )
            result = await self.session.execute(stmt)
            profile = result.scalar_one_or_none()
            if profile:
                return {p.id for p in profile.permissions}

        # Legacy path: map role → system profile name → permissions
        profile_name = _LEGACY_ROLE_PROFILE_MAP.get(key.role)
        if profile_name:
            stmt = (
                select(ProfileORM)
                .options(selectinload(ProfileORM.permissions))
                .where(ProfileORM.name == profile_name)
            )
            result = await self.session.execute(stmt)
            profile = result.scalar_one_or_none()
            if profile:
                return {p.id for p in profile.permissions}

        return set()

    async def revoke_key(self, key_id: str, customer_id: str) -> bool:
        stmt = (
            update(ApiKeyORM)
            .where(ApiKeyORM.id == key_id, ApiKeyORM.customer_id == customer_id)
            .values(is_active=False)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def rotate_key(
        self, key_id: str, customer_id: str
    ) -> Optional[Tuple[str, ApiKeyORM]]:
        # Load old key
        stmt = select(ApiKeyORM).where(
            ApiKeyORM.id == key_id,
            ApiKeyORM.customer_id == customer_id,
            ApiKeyORM.is_active == True,
        )
        result = await self.session.execute(stmt)
        old_key = result.scalar_one_or_none()
        if not old_key:
            return None
        # Revoke old
        old_key.is_active = False
        # Create new with same metadata
        raw_key, new_key = await self.create_key(
            customer_id=old_key.customer_id,
            name=old_key.name,
            role=old_key.role,
            created_by=old_key.created_by,
            expires_at=old_key.expires_at,
            profile_id=old_key.profile_id,
            created_by_user_id=old_key.created_by_user_id,
        )
        return raw_key, new_key

    async def list_keys(self, customer_id: str) -> List[ApiKeyORM]:
        stmt = (
            select(ApiKeyORM)
            .where(ApiKeyORM.customer_id == customer_id)
            .order_by(ApiKeyORM.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
