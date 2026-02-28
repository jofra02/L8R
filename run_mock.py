import asyncio
import argparse
import sys
import os

# Important: We must patch config before importing the graph
from src.config import settings

def main():
    parser = argparse.ArgumentParser(description="Run Support AI Agent with a mock ticket")
    parser.add_argument("--file", "-f", type=str, required=True, help="Path to the plain text file containing the mock ticket")
    parser.add_argument("--fast", action="store_true", help="Enable TEST_MODE_FAST to reduce iterations and LLM outputs")
    
    args = parser.parse_args()
    
    if args.fast:
        print("[!] Enabling FAST TEST MODE limits (1 hypothesis, fewer retries).")
        settings.TEST_MODE_FAST = True
        
    if not os.path.exists(args.file):
        print(f"Error: File '{args.file}' not found.")
        sys.exit(1)
        
    try:
        with open(args.file, "r", encoding="utf-8") as f:
            ticket_text = f.read().strip()
    except UnicodeDecodeError:
        with open(args.file, "r", encoding="utf-16") as f:
            ticket_text = f.read().strip()
        
    if not ticket_text:
        print("Error: Ticket file is empty.")
        sys.exit(1)
        
    print(f"--- Loaded Ticket from {args.file} ({len(ticket_text)} chars) ---")
    
    # Import app after settings are patched
    from src.agent_graph import app
    from src.core.models import Ticket
    from langchain_core.messages import HumanMessage
    import uuid
    import datetime
    
    mock_ticket = Ticket(
        id=f"MOCK-{uuid.uuid4().hex[:6]}",
        mode="incident",
        text=ticket_text,
        severity="medium",
        source="run_mock_cli",
        timestamps={"created_at": datetime.datetime.now().isoformat()}
    )
    
    initial_state = {
        "ticket": mock_ticket,
        "customer_id": "fake_client",
        "messages": [HumanMessage(content=ticket_text)],
        "client_context": None,
        "classification": None,
        "components": [],
        "evidence_refs": [],
        "missing_info": [],
        "facts": {},
        "hypotheses": [],
        "scoring": None,
        "plan": None,
        "topology_nodes": [],
        "topology_edges": [],
        "path_analysis": None,
        "final_answer": "",
        "handoff": None,
        "pending_requirements": [],
        "meta": {"iterations": 0}
    }
    
    print("\n[>] Seeding Database for Mock Test...")
    from src.core.database import async_session_factory
    from src.core.orm import TicketORM, PlatformTenant
    from src.core.audit import AuditService
    from src.utils.logger import setup_logging
    from src.core.registry import CapabilityRegistry
    import logging

    setup_logging()
    logger = logging.getLogger(__name__)

    async def seed_and_run():
        logger.info("Loading Capabilities...")
        CapabilityRegistry.load_builtin_packs()
        await CapabilityRegistry.load_external_tools()
        
        # Bootstrap ALL Qdrant collections + indexes
        from src.core.qdrant import vector_store
        logger.info("Ensuring all Qdrant collections exist...")
        await vector_store.ensure_all_collections()
        
        # Index tools in Qdrant tool_catalog for semantic search
        logger.info("Indexing tools in tool_catalog for semantic search...")
        await CapabilityRegistry.index_tools_for_tenant(initial_state["customer_id"])
        
        # Setup DB references
        async with async_session_factory() as session:
            # 1. Ensure Tenant exists
            tenant = await session.get(PlatformTenant, "fake_client")
            if not tenant:
                print("    Creating missing PlatformTenant 'fake_client'...")
                tenant = PlatformTenant(customer_id="fake_client", name="Mock Test Client")
                session.add(tenant)
                await session.commit()
            
            # 2. Insert Ticket
            t_orm = TicketORM(
                id=mock_ticket.id,
                customer_id="fake_client",
                mode=mock_ticket.mode,
                severity=mock_ticket.severity,
                source=mock_ticket.source,
                text=mock_ticket.text,
                updated_at=datetime.datetime.now()
            )
            session.add(t_orm)
            await session.commit()
            
        print("    DB seeded.")
        
        # Setup Audit
        audit = AuditService()
        trace_id = str(uuid.uuid4())
        run_id = await audit.create_run(mock_ticket.id, trace_id, customer_id="fake_client")
        
        initial_state["meta"]["run_id"] = run_id
        initial_state["meta"]["trace_id"] = trace_id

        print("\n[>] Starting LangGraph Execution...")
        
        final_state = await app.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "mock_thread"}}
        )
        
        print("\n" + "="*80)
        print("FINAL REPORT GENERATED")
        print("="*80)
        print(final_state.get("final_answer", "No report generated."))
        print("="*80)
        
        # Save output to audit history
        try:
            serializable_state = audit._sanitize(final_state)
            await audit.update_run_context(run_id, "fake_client", serializable_state)
            await audit.complete_run(run_id, status="completed")
        except Exception as e:
            logger.error(f"Failed to save final state to database in mock: {e}")

    asyncio.run(seed_and_run())

if __name__ == "__main__":
    main()
