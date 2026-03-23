import asyncio
import logging
import uuid
import sys
from src.config import settings
from src.utils.logger import setup_logging
from src.core.registry import CapabilityRegistry
from src.agent_graph import app
from src.core.models import GlobalState, Ticket, ClientContext
from datetime import datetime

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

async def main():
    """Main entry point."""
    logger.info(f"Starting {settings.APP_NAME} in {settings.APP_ENV} mode.")
    
    # 1. Load Capabilities
    CapabilityRegistry.load_builtin_packs()
    await CapabilityRegistry.load_external_tools()
    logger.info(f"Loaded {len(CapabilityRegistry.list_tools())} tools.")
    
    # Check CLI args for simple run
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        # --- Testing ---
        if cmd == "test":
            await run_test_ticket()
            
        # --- Ops ---
        elif cmd == "init-db":
            await init_db()
            
        elif cmd == "register-tenant":
            # Usage: uv run python src/main.py register-tenant --file <path>
            # For simplicity we assume --file as 3rd arg
            if len(sys.argv) < 4:
                print("Usage: register-tenant --file <path>")
                return
            from src.utils.seed_context import seed_tenant
            await seed_tenant(sys.argv[3])
            
        elif cmd == "seed-context":
            if len(sys.argv) < 4:
                print("Usage: seed-context --file <path>")
                return
            from src.utils.seed_context import seed_context
            await seed_context(sys.argv[3])

        elif cmd == "seed-kb":
            if len(sys.argv) < 6:
                print("Usage: seed-kb --dir <path> --customer-id <id>")
                return
            # Parse args manually for now
            dir_path = sys.argv[3]
            cid = sys.argv[5] 
            from src.utils.seed_kb import seed_kb
            await seed_kb(dir_path, cid)
            
        elif cmd == "create-admin-key":
            await create_admin_key()

        elif cmd == "create-tenant-key":
            await create_tenant_key()

        elif cmd == "create-admin":
            await create_admin_user()

        else:
            logger.info("Unknown command.")
            logger.info("Available: test, init-db, register-tenant, seed-context, seed-kb, create-admin-key, create-tenant-key, create-admin")
    else:
        logger.info("Usage: python src/main.py [command]")
        # In future: uvicorn.run(app)

async def init_db():
    """Initialize databases."""
    logger.info("Initializing Databases...")
    
    # 1. Postgres migrations are handled by alembic externally for now.
    logger.info("Ensure you have run 'uv run alembic upgrade head' for Postgres.")

    # 2. Qdrant Initialization (collections + payload indexes)
    try:
        from src.core.qdrant import vector_store
        await vector_store.ensure_all_collections()
        logger.info("Qdrant collections and indexes ensured.")
    except Exception as e:
        logger.error(f"Failed to initialize Qdrant: {e}")

async def run_test_ticket():
    """Run a simulated ticket through the graph."""
    logger.info("Running test ticket...")
    
    # Mock Input
    ticket = Ticket(
        id=str(uuid.uuid4()),
        mode="incident",
        text="Los usuario en la subred 192.168.241.0 no puede llegar a la pagina principal de AWS, les da error de conectividad a traves del FortiGate",
        severity="medium",
        source="cli_test",
        timestamps={"created_at": datetime.now().isoformat()}
    )
    
    # Mock Context (In real app, fetched by ContextAgent, but we can seed it)
    # The ContextAgent node will actually fetch it, so we start with minimal state.
    initial_state = GlobalState(
        ticket=ticket,
        customer_id="fake_client",
        client_context=None, # To be fetched
        classification=None,
        components=[],
        facts={},
        evidence_refs=[],
        missing_info=[],
        hypotheses=[],
        plan=None,
        topology_nodes=[],
        topology_edges=[],
        path_analysis=None,
        final_answer="",
        handoff=None,
        meta={"iterations": 0}
    )

    # Persist Ticket (Required for Audit FK)
    from src.core.database import async_session_factory
    from src.core.orm import TicketORM, PlatformTenant
    
    async with async_session_factory() as session:
        # 0. Ensure Tenant exists (Just to be safe, but it should be there)
        tenant = await session.get(PlatformTenant, "fake_client")
        if not tenant:
             logger.warning("Tenant fake_client not found in DB during test! This might cause issues if not seeded.")
        
        # 2. Upsert Ticket
        # distinct ticket for every test run
        t_orm = TicketORM(
            id=ticket.id,
            customer_id="fake_client", # Matches tenant
            mode=ticket.mode,
            severity=ticket.severity,
            source=ticket.source,
            text=ticket.text,
            updated_at=datetime.now()
        )
        session.add(t_orm)
        await session.commit()

    # Audit: Start Run
    from src.core.audit import AuditService
    audit = AuditService()
    # Use a trace_id if available or generate one
    trace_id = str(uuid.uuid4())
    run_id = await audit.create_run(ticket.id, trace_id, customer_id="fake_client")
    
    # Run Graph
    initial_state["meta"]["run_id"] = run_id
    initial_state["meta"]["trace_id"] = trace_id
    try:
        output = await app.ainvoke(initial_state)
        
        # Save output to audit history
        try:
            serializable_state = audit._sanitize(output)
            await audit.update_run_context(run_id, "fake_client", serializable_state)
            await audit.complete_run(run_id, "completed")
        except Exception as e:
            logger.error(f"Failed to save final state to database in mock: {e}")
            
    except Exception as e:
        logger.error(f"Graph execution failed: {e}")
        await audit.complete_run(run_id, "failed")
        return
    
    print("\n" + "="*50)
    print(f"FINAL ANSWER:\n{output.get('final_answer')}")
    print("="*50)
    
    if output.get("plan"):
        print("\nPLAN Generated:")
        for step in output["plan"].diagnosis_steps:
            print(f"- {step.tool}: {step.description}")

async def create_admin_key():
    """Bootstrap the first platform_admin API key."""
    from src.core.database import async_session_factory
    from src.core.orm import PlatformTenant
    from src.api.services.auth_service import AuthService

    async with async_session_factory() as session:
        # Ensure __platform__ tenant exists
        tenant = await session.get(PlatformTenant, "__platform__")
        if not tenant:
            session.add(PlatformTenant(
                customer_id="__platform__",
                name="Platform Admin",
                status="active",
                plan="platform",
            ))
            await session.commit()
            logger.info("Created __platform__ tenant.")

        service = AuthService(session)

        name = "bootstrap-admin"
        if len(sys.argv) > 2:
            name = sys.argv[2]

        raw_key, key_orm = await service.create_key(
            customer_id="__platform__",
            name=name,
        )

    print("\n" + "=" * 60)
    print("Platform Admin API Key Created")
    print("=" * 60)
    print(f"  Key ID:   {key_orm.id}")
    print(f"  Name:     {key_orm.name}")
    print(f"  Raw Key:  {raw_key}")
    print("=" * 60)
    print("SAVE THIS KEY — it will not be shown again.")
    print("=" * 60 + "\n")


async def create_tenant_key():
    """Create an API key for an existing tenant (ticket ingestion only).

    Usage:
        create-tenant-key <customer_id> [name]
    Examples:
        create-tenant-key fake_client
        create-tenant-key fake_client "CI Key"
    """
    if len(sys.argv) < 3:
        print("Usage: create-tenant-key <customer_id> [name]")
        print("  name:  key display name  (default: 'default')")
        return

    customer_id = sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else "default"

    from src.core.database import async_session_factory
    from src.core.orm import PlatformTenant
    from src.api.services.auth_service import AuthService

    async with async_session_factory() as session:
        tenant = await session.get(PlatformTenant, customer_id)
        if not tenant:
            print(f"Tenant '{customer_id}' not found. Register it first with register-tenant.")
            return

        service = AuthService(session)
        raw_key, key_orm = await service.create_key(
            customer_id=customer_id,
            name=name,
        )

    print("\n" + "=" * 60)
    print(f"Tenant API Key Created")
    print("=" * 60)
    print(f"  Tenant:   {customer_id}")
    print(f"  Key ID:   {key_orm.id}")
    print(f"  Name:     {key_orm.name}")
    print(f"  Raw Key:  {raw_key}")
    print("=" * 60)
    print("SAVE THIS KEY — it will not be shown again.")
    print("=" * 60 + "\n")


async def create_admin_user():
    """Create a Super Admin user account.

    Usage:
        create-admin [email]
    Examples:
        create-admin
        create-admin admin@mycompany.com
    """
    import secrets

    email = sys.argv[2] if len(sys.argv) > 2 else settings.BOOTSTRAP_ADMIN_EMAIL
    password = secrets.token_urlsafe(16)

    from src.core.database import async_session_factory
    from src.api.services.user_service import UserService

    async with async_session_factory() as session:
        service = UserService(session)

        existing = await service.get_user_by_email(email)
        if existing:
            print(f"User '{email}' already exists (id={existing.id}).")
            return

        user = await service.create_user(
            email=email,
            display_name="Super Admin",
            password=password,
            is_platform_admin=True,
            must_change_password=True,
        )

    print("\n" + "=" * 60)
    print("Super Admin User Created")
    print("=" * 60)
    print(f"  Email:    {email}")
    print(f"  Password: {password}")
    print(f"  User ID:  {user.id}")
    print("  (password change will be required on first login)")
    print("=" * 60)
    print("SAVE THIS PASSWORD — it will not be shown again.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
