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
            
        elif cmd == "resume":
            # Usage: resume --file needs.json --state paused_state.json
            import json
            
            # Simple arg parsing
            try:
                file_idx = sys.argv.index("--file") + 1
                needs_path = sys.argv[file_idx]
                state_idx = sys.argv.index("--state") + 1
                state_path = sys.argv[state_idx]
            except ValueError:
                print("Usage: resume --file <needs.json> --state <paused_state.json>")
                return

            await resume_execution(needs_path, state_path)

        else:
            logger.info("Unknown command.")
            logger.info("Available: test, init-db, register-tenant, seed-context, seed-kb, resume")
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

async def resume_execution(needs_path: str, state_path: str):
    """Resumes execution from a paused state with user inputs."""
    logger.info(f"Resuming execution with inputs from {needs_path}...")
    
    import json
    
    # 1. Load State
    try:
        with open(state_path, "r") as f:
            state = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load state: {e}")
        return

    # 2. Load User Inputs
    try:
        with open(needs_path, "r") as f:
            user_input_data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load needs file: {e}")
        return
        
    # 3. Process Inputs
    # Expect user_input_data['required_inputs'] with "key" and "value"
    updates = {}
    
    # Support new format
    if "required_inputs" in user_input_data:
         for item in user_input_data["required_inputs"]:
             if item.get("value") is not None: # User provided value
                 updates[item["key"]] = item["value"]

    # Support legacy format (just in case)
    elif "missing_info" in user_input_data:
        for item in user_input_data["missing_info"]:
            if "value" in item and item["value"]:
                updates[item["key"]] = item["value"]
    
    # Inject into facts
    if "facts" not in state:
        state["facts"] = {}
    
    logger.info(f"Injecting User Facts: {updates}")
    state["facts"].update(updates)
    
    # 4. Clear Pending Requirements (Unblock)
    state["pending_requirements"] = []
    
    # 5. Run Graph
    # We must RE-RUN the graph. 
    # Since we are not using a Persistent Checkpointer that knows exactly where we were,
    # we are essentially starting a new run but with a "hot" state.
    # The Supervisor should see `pending_requirements` is empty, and route to `evidence_collector` 
    # (or wherever appropriate based on evidence/hypotheses).
    
    # Important: Re-constitute Pydantic models from dicts if needed?
    # LangGraph/LangChain usually handles dict state if TypedDict is used.
    # But some agents expect objects (like Ticket).
    # We might need to deserialization logic similar to 'Ticket(**state["ticket"])'
    # For this prototype, let's assume dict access works (most agents use .get or dict access).
    # IF agents use .attribute access, this will fail.
    # Checking code... agents use `state.get("ticket").text` or `state["ticket"].text`.
    # Ticket IS a Pydantic model in the code.
    # We need to re-hydrate Pydantic models.
    
    from src.core.models import Ticket, Component, EvidenceSnapshot, Hypothesis, Classification, Plan
    
    if isinstance(state.get("ticket"), dict):
        state["ticket"] = Ticket(**state["ticket"])
        
    if state.get("components"):
        state["components"] = [Component(**c) if isinstance(c, dict) else c for c in state["components"]]
        
    if state.get("hypotheses"):
         state["hypotheses"] = [Hypothesis(**h) if isinstance(h, dict) else h for h in state["hypotheses"]]

    if state.get("evidence_refs"):
         state["evidence_refs"] = [EvidenceSnapshot(**e) if isinstance(e, dict) else e for e in state["evidence_refs"]]
         
    if isinstance(state.get("classification"), dict):
        state["classification"] = Classification(**state["classification"])
        
    if isinstance(state.get("plan"), dict):
        state["plan"] = Plan(**state["plan"])

    # 6. Reset Iterations to give the agent time to think with new info
    if "meta" in state:
        state["meta"]["iterations"] = 0
        logger.info("Iterations reset to 0 for resume.")

    # 7. Execute
    output = await app.ainvoke(state)
    
    print("\n" + "="*50)
    print(f"FINAL ANSWER (RESUMED):\n{output.get('final_answer')}")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(main())
