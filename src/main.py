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
    logger.info(f"Loaded {len(CapabilityRegistry.list_tools())} tools.")
    
    # Check CLI args for simple run
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        await run_test_ticket()
    else:
        logger.info("Usage: python src/main.py test")
        # In future: uvicorn.run(app)

async def run_test_ticket():
    """Run a simulated ticket through the graph."""
    logger.info("Running test ticket...")
    
    # Mock Input
    ticket = Ticket(
        id=str(uuid.uuid4()),
        mode="incident",
        text="Cannot access the main web server (192.168.1.10). It seems down.",
        severity="medium",
        source="cli_test",
        timestamps={"created_at": datetime.now().isoformat()}
    )
    
    # Mock Context (In real app, fetched by ContextAgent, but we can seed it)
    # The ContextAgent node will actually fetch it, so we start with minimal state.
    initial_state = GlobalState(
        ticket=ticket,
        customer_id="cust_12345",
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
    
    # Run Graph
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
