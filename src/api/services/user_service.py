import re
import uuid
from datetime import datetime, timezone
from typing import Optional, List

import bcrypt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.core.orm import UserORM, UserTenantProfileORM, ProfileORM, RefreshTokenORM
from src.api.services.jwt_service import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
)


def validate_password(password: str) -> str:
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters")
    if settings.PASSWORD_REQUIRE_UPPERCASE and not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if settings.PASSWORD_REQUIRE_SYMBOL and not re.search(r"[^a-zA-Z0-9]", password):
        raise ValueError("Password must contain at least one symbol")
    return password


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(
        self,
        email: str,
        display_name: str,
        password: str,
        is_platform_admin: bool = False,
        must_change_password: bool = False,
    ) -> UserORM:
        validate_password(password)
        user = UserORM(
            id=str(uuid.uuid4()),
            email=email.lower().strip(),
            display_name=display_name,
            password_hash=_hash_password(password),
            is_platform_admin=is_platform_admin,
            must_change_password=must_change_password,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_user(self, user_id: str) -> Optional[UserORM]:
        stmt = (
            select(UserORM)
            .options(selectinload(UserORM.tenant_profiles).selectinload(UserTenantProfileORM.profile))
            .where(UserORM.id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[UserORM]:
        stmt = select(UserORM).where(UserORM.email == email.lower().strip())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_users(self, is_active: Optional[bool] = None) -> List[UserORM]:
        stmt = select(UserORM).order_by(UserORM.created_at.desc())
        if is_active is not None:
            stmt = stmt.where(UserORM.is_active == is_active)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_user(self, user_id: str, **fields) -> Optional[UserORM]:
        if "password" in fields:
            password = fields.pop("password")
            validate_password(password)
            fields["password_hash"] = _hash_password(password)
        if not fields:
            return await self.get_user(user_id)
        stmt = update(UserORM).where(UserORM.id == user_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.commit()
        return await self.get_user(user_id)

    async def deactivate_user(self, user_id: str) -> bool:
        stmt = update(UserORM).where(UserORM.id == user_id).values(is_active=False)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def authenticate(
        self, email: str, password: str, customer_id: Optional[str] = None
    ) -> Optional[dict]:
        """
        Authenticate user. Returns dict with tokens + user info, or None.
        If customer_id is provided, scopes permissions to that tenant.
        Otherwise, picks the first available tenant.
        """
        user = await self.get_user_by_email(email)
        if not user or not user.is_active:
            return None
        if not _verify_password(password, user.password_hash):
            return None

        # Update last_login_at
        await self.session.execute(
            update(UserORM).where(UserORM.id == user.id).values(last_login_at=datetime.now(timezone.utc))
        )

        # Resolve permissions for the target tenant
        permissions: list[str] = []
        active_customer_id = customer_id
        available_tenants: list[str] = []

        if user.is_platform_admin:
            # Platform admins get all permissions regardless
            from src.core.orm import PermissionORM
            perm_stmt = select(PermissionORM.id)
            perm_result = await self.session.execute(perm_stmt)
            permissions = list(perm_result.scalars().all())
            # Get all tenants
            from src.core.orm import PlatformTenant
            tenant_stmt = select(PlatformTenant.customer_id)
            tenant_result = await self.session.execute(tenant_stmt)
            available_tenants = list(tenant_result.scalars().all())
            if not active_customer_id and available_tenants:
                active_customer_id = available_tenants[0]
        else:
            # Load tenant profiles
            tp_stmt = (
                select(UserTenantProfileORM)
                .options(selectinload(UserTenantProfileORM.profile).selectinload(ProfileORM.permissions))
                .where(UserTenantProfileORM.user_id == user.id)
            )
            tp_result = await self.session.execute(tp_stmt)
            tenant_profiles = list(tp_result.scalars().all())
            available_tenants = [tp.customer_id for tp in tenant_profiles]

            if not active_customer_id and tenant_profiles:
                active_customer_id = tenant_profiles[0].customer_id

            # Find profile for active tenant
            for tp in tenant_profiles:
                if tp.customer_id == active_customer_id:
                    permissions = [p.id for p in tp.profile.permissions]
                    break

        if not active_customer_id:
            active_customer_id = "__none__"

        # Create tokens — platform admins use sentinel so middleware can apply tenant override
        access_token = create_access_token(
            user_id=user.id,
            customer_id="__platform__" if user.is_platform_admin else active_customer_id,
            permissions=permissions,
            is_platform_admin=user.is_platform_admin,
            must_change_password=user.must_change_password,
        )
        raw_refresh, refresh_hash, refresh_expires = create_refresh_token()

        # Persist refresh token
        refresh_orm = RefreshTokenORM(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=refresh_expires,
        )
        self.session.add(refresh_orm)
        await self.session.commit()

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "must_change_password": user.must_change_password,
            "user": {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "is_platform_admin": user.is_platform_admin,
                "customer_id": active_customer_id,
                "available_tenants": available_tenants,
            },
        }

    async def refresh_access_token(self, raw_refresh_token: str) -> Optional[dict]:
        """Validate refresh token and issue new access token."""
        token_hash = hash_refresh_token(raw_refresh_token)
        stmt = (
            select(RefreshTokenORM)
            .where(
                RefreshTokenORM.token_hash == token_hash,
                RefreshTokenORM.is_revoked == False,
            )
        )
        result = await self.session.execute(stmt)
        refresh = result.scalar_one_or_none()
        if not refresh:
            return None
        if refresh.expires_at < datetime.now(timezone.utc):
            return None

        user = await self.get_user(refresh.user_id)
        if not user or not user.is_active:
            return None

        # Resolve permissions (same logic as authenticate)
        permissions: list[str] = []
        available_tenants: list[str] = []
        active_customer_id = "__none__"

        if user.is_platform_admin:
            from src.core.orm import PermissionORM, PlatformTenant
            perm_result = await self.session.execute(select(PermissionORM.id))
            permissions = list(perm_result.scalars().all())
            tenant_result = await self.session.execute(select(PlatformTenant.customer_id))
            available_tenants = list(tenant_result.scalars().all())
            if available_tenants:
                active_customer_id = available_tenants[0]
        else:
            tp_stmt = (
                select(UserTenantProfileORM)
                .options(selectinload(UserTenantProfileORM.profile).selectinload(ProfileORM.permissions))
                .where(UserTenantProfileORM.user_id == user.id)
            )
            tp_result = await self.session.execute(tp_stmt)
            tenant_profiles = list(tp_result.scalars().all())
            available_tenants = [tp.customer_id for tp in tenant_profiles]
            if tenant_profiles:
                active_customer_id = tenant_profiles[0].customer_id
                permissions = [p.id for p in tenant_profiles[0].profile.permissions]

        access_token = create_access_token(
            user_id=user.id,
            customer_id="__platform__" if user.is_platform_admin else active_customer_id,
            permissions=permissions,
            is_platform_admin=user.is_platform_admin,
            must_change_password=user.must_change_password,
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def revoke_refresh_token(self, raw_refresh_token: str) -> bool:
        token_hash = hash_refresh_token(raw_refresh_token)
        stmt = (
            update(RefreshTokenORM)
            .where(RefreshTokenORM.token_hash == token_hash)
            .values(is_revoked=True)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def change_password(self, user_id: str, current_password: str, new_password: str) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        if not _verify_password(current_password, user.password_hash):
            return False
        validate_password(new_password)
        new_hash = _hash_password(new_password)
        await self.session.execute(
            update(UserORM)
            .where(UserORM.id == user_id)
            .values(password_hash=new_hash, must_change_password=False)
        )
        await self.session.commit()
        return True

    async def admin_reset_password(self, user_id: str, new_password: str) -> bool:
        validate_password(new_password)
        stmt = (
            update(UserORM)
            .where(UserORM.id == user_id)
            .values(password_hash=_hash_password(new_password), must_change_password=True)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0
