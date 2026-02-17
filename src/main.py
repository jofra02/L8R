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
            
        else:
            logger.info("Unknown command.")
            logger.info("Available: test, init-db, register-tenant, seed-context, seed-kb")
    else:
        logger.info("Usage: python src/main.py [command]")
        # In future: uvicorn.run(app)

async def init_db():
    """Initialize databases."""
    logger.info("Initializing Databases...")
    
    # 1. Postgres migrations are handled by alembic externally for now.
    logger.info("Ensure you have run 'uv run alembic upgrade head' for Postgres.")

    # 2. Qdrant Initialization
    try:
        from src.core.qdrant import vector_store
        await vector_store.ensure_collection("knowledge_base", vector_size=1536)
        logger.info("Qdrant 'knowledge_base' collection ensured.")
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
    run_id = await audit.create_run(ticket.id, trace_id)
    
    # Run Graph
    initial_state["meta"]["run_id"] = run_id
    initial_state["meta"]["trace_id"] = trace_id
    output = await app.ainvoke(initial_state)
    
    print("\n" + "="*50)
    print(f"FINAL ANSWER:\n{output.get('final_answer')}")
    print("="*50)
    
    if output.get("plan"):
        print("\nPLAN Generated:")
        for step in output["plan"].diagnosis_steps:
            print(f"- {step.tool}: {step.description}")

if __name__ == "__main__":
    asyncio.run(main())
