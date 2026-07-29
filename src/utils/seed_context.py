import yaml
import asyncio
import sys
from typing import Dict, Any
from src.core.database import async_session_factory
from src.core.orm import PlatformTenant, CapabilityScope, ClientContextORM
from src.core.models import ClientContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

async def seed_tenant(file_path: str):
    """Register a tenant in the Control Plane."""
    print(f"Reading Tenant YAML: {file_path}")
    with open(file_path, "r") as f:
        data = yaml.safe_load(f)
    
    customer_id = data["id"]
    print(f"Processing customer: {customer_id}")
    
    # Debug: Print MRO or Mapper info
    try:
        from sqlalchemy import inspect
        print(f"Inspecting PlatformTenant: {inspect(PlatformTenant).local_table}")
    except Exception as e:
        print(f"Inspection Failed: {e}")
        import traceback
        traceback.print_exc()
        return

    async with async_session_factory() as session:
        # Check if exists
        result = await session.execute(select(PlatformTenant).where(PlatformTenant.customer_id == customer_id))
        tenant = result.scalar_one_or_none()
        
        if not tenant:
            tenant = PlatformTenant(customer_id=customer_id)
            session.add(tenant)
        
        # Update fields
        tenant.name = data.get("name", tenant.customer_id)
        tenant.status = data.get("status", "active")
        tenant.plan = data.get("plan", "standard")
        
        # Upsert the 'default' scope (uq_scope_per_tenant makes re-seeding
        # fail otherwise)
        allowed = data.get("allowed_tools", [])
        if allowed:
            scope_res = await session.execute(
                select(CapabilityScope).where(
                    CapabilityScope.customer_id == customer_id,
                    CapabilityScope.scope_name == "default",
                )
            )
            scope = scope_res.scalar_one_or_none()
            if scope:
                scope.allowed_tools = allowed
            else:
                session.add(CapabilityScope(
                    customer_id=customer_id,
                    scope_name="default",
                    allowed_tools=allowed
                ))

        await session.commit()
        print(f"Tenant {customer_id} registered/updated.")

    # Best-effort MCP gateway inventory provisioning (never fails the seed)
    from src.api.services.gateway_admin_client import GatewayAdminClient
    gateway = GatewayAdminClient.from_settings()
    if not gateway:
        print("Gateway sync skipped (MCP_GATEWAY_ADMIN_URL/TOKEN not configured).")
        return
    sync = await gateway.create_tenant(customer_id, tenant.name)
    if sync.status == "synced":
        print(f"Gateway inventory provisioned for {customer_id}.")
    else:
        print(f"Gateway inventory sync {sync.status}: {sync.error or ''}")

async def seed_context(file_path: str):
    """Seed ClientContext in the Data Plane.

    Components and dependencies are seeded into the relational asset tables
    (AssetService) — the assets tables are authoritative since the Asset
    Inventory migration. The blob keeps baselines/known_changes.
    """
    print(f"Reading Context YAML: {file_path}")
    with open(file_path, "r") as f:
        data = yaml.safe_load(f)

    customer_id = data["customer_id"]

    # Validate against Pydantic Model
    try:
        context_model = ClientContext(**data)
    except Exception as e:
        print(f"Validation Failed: {e}")
        return

    async with async_session_factory() as session:
        # Check if tenant exists/active (Guardrail)
        tenant_res = await session.execute(select(PlatformTenant).where(PlatformTenant.customer_id == customer_id))
        tenant = tenant_res.scalar_one_or_none()

        if not tenant or tenant.status != 'active':
            print(f"Error: Tenant {customer_id} not found or inactive in Control Plane.")
            return

        # Components/dependencies -> asset tables (upsert by id, lenient).
        from src.api.schemas.inventory import ComponentCreate, DependencyCreate
        from src.api.services.inventory_service import InventoryService
        from src.api.exceptions import APIError

        inventory = InventoryService(session)
        for comp in context_model.inventory:
            payload = ComponentCreate(**comp.model_dump())
            try:
                await inventory.add_component(customer_id, payload)
                print(f"  asset created: {comp.id}")
            except APIError as e:
                if e.error == "conflict":
                    from src.api.schemas.inventory import ComponentUpdate
                    await inventory.update_component(
                        customer_id, comp.id,
                        ComponentUpdate(**comp.model_dump(exclude={"id"})),
                    )
                    print(f"  asset updated: {comp.id}")
                else:
                    print(f"  asset {comp.id} skipped: {e.error} {e.detail}")
        for dep in context_model.dependencies:
            try:
                await inventory.add_dependency(customer_id, DependencyCreate(**dep.model_dump()))
                print(f"  relation created: {dep.source_id} -> {dep.target_id}")
            except APIError as e:
                if e.error != "conflict":
                    print(f"  relation skipped: {e.error} {e.detail}")

        # Blob keeps baselines/known_changes (inventory keys are blanked by
        # ContextStore on save; here we upsert the row directly).
        content = context_model.model_dump()
        content["inventory"] = []
        content["dependencies"] = []

        stmt = select(ClientContextORM).where(
            ClientContextORM.customer_id == customer_id,
            ClientContextORM.version == context_model.version
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.content = content
            print(f"Updated existing context version {context_model.version}")
        else:
            new_ctx = ClientContextORM(
                customer_id=customer_id,
                version=context_model.version,
                content=content,
                is_active=True
            )
            session.add(new_ctx)
            print(f"Created new context version {context_model.version}")

        await session.commit()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python seed_context.py [tenant|context] <file>")
        sys.exit(1)
        
    mode = sys.argv[1]
    file = sys.argv[2]
    
    if mode == "tenant":
        asyncio.run(seed_tenant(file))
    elif mode == "context":
        asyncio.run(seed_context(file))
    else:
        print("Unknown mode")
