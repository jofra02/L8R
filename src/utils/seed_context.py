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
        
        # Update Scopes
        # Simple Logic: Clear existing and re-add for now, or merge.
        # MVP: just add a default scope if none
        allowed = data.get("allowed_tools", [])
        if allowed:
            # Check if scope exists
            # We will just append a 'default' scope for now
            # In real impl, handle existing scopes better
            scope = CapabilityScope(
                customer_id=customer_id,
                scope_name="default",
                allowed_tools=allowed
            )
            session.add(scope)

        await session.commit()
        print(f"Tenant {customer_id} registered/updated.")

async def seed_context(file_path: str):
    """Seed ClientContext in the Data Plane."""
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

        # Upsert Context
        # We check for existing version or just overwrite 'latest' logic?
        # For this seeder, we will create a NEW version or update if version matches?
        # Let's simple: Insert new row mapping to this version.
        
        # Check if this version exists
        stmt = select(ClientContextORM).where(
            ClientContextORM.customer_id == customer_id,
            ClientContextORM.version == context_model.version
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.content = context_model.model_dump()
            print(f"Updated existing context version {context_model.version}")
        else:
            new_ctx = ClientContextORM(
                customer_id=customer_id,
                version=context_model.version,
                content=context_model.model_dump(),
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
