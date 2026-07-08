import logging

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Optional, List, Tuple

from src.core.orm import (
    PlatformTenant,
    TenantEndpoint,
    CapabilityScope,
    TicketORM,
    UserTenantProfileORM,
    ApiKeyORM,
)
from src.api.schemas.tenants import EndpointUpsert, ScopeCreate, ScopeUpdate
from src.api.exceptions import APIError
from src.api.services.gateway_admin_client import GatewayAdminClient, GatewaySyncResult

logger = logging.getLogger(__name__)


class TenantService:
    def __init__(self, session: AsyncSession, gateway: Optional[GatewayAdminClient] = None):
        self.session = session
        self.gateway = gateway if gateway is not None else GatewayAdminClient.from_settings()

    # ---- Tenant CRUD ----

    async def list_tenants(self) -> List[dict]:
        user_count_sq = (
            select(func.count())
            .where(UserTenantProfileORM.customer_id == PlatformTenant.customer_id)
            .correlate(PlatformTenant)
            .scalar_subquery()
        )
        ticket_count_sq = (
            select(func.count())
            .where(TicketORM.customer_id == PlatformTenant.customer_id)
            .correlate(PlatformTenant)
            .scalar_subquery()
        )
        last_activity_sq = (
            select(func.max(TicketORM.created_at))
            .where(TicketORM.customer_id == PlatformTenant.customer_id)
            .correlate(PlatformTenant)
            .scalar_subquery()
        )

        stmt = (
            select(
                PlatformTenant,
                user_count_sq.label("user_count"),
                ticket_count_sq.label("ticket_count"),
                last_activity_sq.label("last_activity"),
            )
            .order_by(PlatformTenant.created_at.desc())
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        return [
            {
                "customer_id": row.PlatformTenant.customer_id,
                "name": row.PlatformTenant.name,
                "status": row.PlatformTenant.status,
                "plan": row.PlatformTenant.plan,
                "created_at": row.PlatformTenant.created_at,
                "updated_at": row.PlatformTenant.updated_at,
                "user_count": row.user_count or 0,
                "ticket_count": row.ticket_count or 0,
                "last_activity": row.last_activity,
            }
            for row in rows
        ]

    async def create_tenant(
        self, customer_id: str, name: str, plan: str
    ) -> Tuple[PlatformTenant, GatewaySyncResult]:
        existing = await self.session.get(PlatformTenant, customer_id)
        if existing:
            raise APIError(409, "tenant_exists", f"Tenant '{customer_id}' already exists")

        tenant = PlatformTenant(
            customer_id=customer_id,
            name=name,
            plan=plan,
            status="active",
        )
        self.session.add(tenant)
        await self.session.commit()
        await self.session.refresh(tenant)

        # Best-effort gateway provisioning after the local commit: the tenant
        # must exist app-side even when the gateway is down or unconfigured.
        sync = await self._provision_gateway_tenant(customer_id, name)
        return tenant, sync

    async def _provision_gateway_tenant(self, customer_id: str, name: str) -> GatewaySyncResult:
        if not self.gateway:
            return GatewaySyncResult(status="skipped")
        sync = await self.gateway.create_tenant(customer_id, name)
        if sync.status == "error":
            logger.warning(
                f"Gateway inventory provisioning failed for tenant '{customer_id}': {sync.error}"
            )
        return sync

    async def get_tenant(self, customer_id: str) -> Optional[PlatformTenant]:
        stmt = (
            select(PlatformTenant)
            .where(PlatformTenant.customer_id == customer_id)
            .options(
                selectinload(PlatformTenant.endpoints),
                selectinload(PlatformTenant.scopes),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_tenant_detail(self, customer_id: str) -> Optional[dict]:
        tenant = await self.get_tenant(customer_id)
        if not tenant:
            return None

        user_count = await self._count(
            select(func.count()).where(UserTenantProfileORM.customer_id == customer_id)
        )
        ticket_count = await self._count(
            select(func.count()).where(TicketORM.customer_id == customer_id)
        )
        last_activity = (
            await self.session.execute(
                select(func.max(TicketORM.created_at)).where(TicketORM.customer_id == customer_id)
            )
        ).scalar()

        return {
            "customer_id": tenant.customer_id,
            "name": tenant.name,
            "status": tenant.status,
            "plan": tenant.plan,
            "created_at": tenant.created_at,
            "updated_at": tenant.updated_at,
            "user_count": user_count,
            "ticket_count": ticket_count,
            "last_activity": last_activity,
            "endpoints": tenant.endpoints,
            "scopes": list(tenant.scopes),
        }

    async def update_tenant(self, customer_id: str, **fields) -> Optional[PlatformTenant]:
        tenant = await self.session.get(PlatformTenant, customer_id)
        if not tenant:
            return None
        for k, v in fields.items():
            setattr(tenant, k, v)
        await self.session.commit()
        await self.session.refresh(tenant)
        return tenant

    async def suspend_tenant(self, customer_id: str) -> Optional[PlatformTenant]:
        return await self.update_tenant(customer_id, status="suspended")

    async def activate_tenant(self, customer_id: str) -> Optional[PlatformTenant]:
        return await self.update_tenant(customer_id, status="active")

    async def get_cascade_counts(self, customer_id: str) -> dict:
        user_count = await self._count(
            select(func.count()).where(UserTenantProfileORM.customer_id == customer_id)
        )
        ticket_count = await self._count(
            select(func.count()).where(TicketORM.customer_id == customer_id)
        )
        api_key_count = await self._count(
            select(func.count()).where(ApiKeyORM.customer_id == customer_id)
        )
        return {
            "user_count": user_count,
            "ticket_count": ticket_count,
            "api_key_count": api_key_count,
        }

    async def delete_tenant(self, customer_id: str, force: bool = False) -> bool:
        tenant = await self.session.get(PlatformTenant, customer_id)
        if not tenant:
            return False

        counts = await self.get_cascade_counts(customer_id)
        total = counts["user_count"] + counts["ticket_count"] + counts["api_key_count"]

        if total > 0 and not force:
            raise APIError(
                409,
                "has_data",
                f"Tenant '{customer_id}' has {counts['user_count']} users, "
                f"{counts['ticket_count']} tickets, {counts['api_key_count']} API keys. "
                f"Use ?force=true to delete.",
            )

        # Best-effort gateway cleanup before the local delete; the local delete
        # proceeds regardless (a 409 manual_devices_present needs an operator).
        if self.gateway:
            sync = await self.gateway.delete_tenant(customer_id)
            if sync.status == "error":
                logger.warning(
                    f"Gateway inventory delete failed for tenant '{customer_id}': {sync.error}"
                )

        await self.session.delete(tenant)
        await self.session.commit()
        return True

    # ---- Endpoints ----

    async def get_endpoints(self, customer_id: str) -> Optional[TenantEndpoint]:
        return await self.session.get(TenantEndpoint, customer_id)

    async def upsert_endpoints(self, customer_id: str, data: EndpointUpsert) -> TenantEndpoint:
        tenant = await self.session.get(PlatformTenant, customer_id)
        if not tenant:
            raise APIError(404, "not_found", "Tenant not found")

        endpoint = await self.session.get(TenantEndpoint, customer_id)
        if endpoint:
            for k, v in data.model_dump(exclude_unset=True).items():
                setattr(endpoint, k, v)
        else:
            endpoint = TenantEndpoint(customer_id=customer_id, **data.model_dump())
            self.session.add(endpoint)

        await self.session.commit()
        await self.session.refresh(endpoint)
        return endpoint

    # ---- Capability Scopes ----

    async def list_scopes(self, customer_id: str) -> List[CapabilityScope]:
        stmt = (
            select(CapabilityScope)
            .where(CapabilityScope.customer_id == customer_id)
            .order_by(CapabilityScope.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_scope(self, customer_id: str, data: ScopeCreate) -> CapabilityScope:
        tenant = await self.session.get(PlatformTenant, customer_id)
        if not tenant:
            raise APIError(404, "not_found", "Tenant not found")

        existing = await self.session.execute(
            select(CapabilityScope).where(
                CapabilityScope.customer_id == customer_id,
                CapabilityScope.scope_name == data.scope_name,
            )
        )
        if existing.scalar_one_or_none():
            raise APIError(409, "scope_exists", f"Scope '{data.scope_name}' already exists for this tenant")

        scope = CapabilityScope(
            customer_id=customer_id,
            scope_name=data.scope_name,
            allowed_tools=data.allowed_tools,
            rate_limit=data.rate_limit,
        )
        self.session.add(scope)
        await self.session.commit()
        await self.session.refresh(scope)
        return scope

    async def update_scope(self, scope_id: int, customer_id: str, **fields) -> Optional[CapabilityScope]:
        stmt = select(CapabilityScope).where(
            CapabilityScope.id == scope_id,
            CapabilityScope.customer_id == customer_id,
        )
        result = await self.session.execute(stmt)
        scope = result.scalar_one_or_none()
        if not scope:
            return None
        for k, v in fields.items():
            setattr(scope, k, v)
        await self.session.commit()
        await self.session.refresh(scope)
        return scope

    async def delete_scope(self, scope_id: int, customer_id: str) -> bool:
        stmt = select(CapabilityScope).where(
            CapabilityScope.id == scope_id,
            CapabilityScope.customer_id == customer_id,
        )
        result = await self.session.execute(stmt)
        scope = result.scalar_one_or_none()
        if not scope:
            return False
        await self.session.delete(scope)
        await self.session.commit()
        return True

    # ---- Helpers ----

    async def _count(self, stmt) -> int:
        result = await self.session.execute(stmt)
        return result.scalar() or 0
