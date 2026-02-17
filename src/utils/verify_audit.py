from src.core.database import get_session
from src.core.orm import AgentRunORM, AgentEventORM
from sqlalchemy import select, desc
import asyncio
import logging

# Setup basic logging to see output
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_audit():
    print("--- Verifying Audit System ---")
    
    async with get_session() as session:
        # 1. Check for latest AgentRun
        stmt = select(AgentRunORM).order_by(desc(AgentRunORM.started_at)).limit(1)
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        
        if not run:
            print("FAILURE: No AgentRun found.")
            return

        print(f"SUCCESS: Found Run ID: {run.id}")
        print(f"  - Status: {run.status}")
        print(f"  - Ticket ID: {run.ticket_id}")
        print(f"  - Customer ID: {run.customer_id}")
        
        # 2. Check for AgentEvents
        stmt_events = select(AgentEventORM).where(AgentEventORM.run_id == run.id).order_by(AgentEventORM.id)
        result_events = await session.execute(stmt_events)
        events = result_events.scalars().all()
        
        if not events:
            print("FAILURE: No AgentEvents found for this run.")
        else:
            print(f"SUCCESS: Found {len(events)} AgentEvents.")
            for e in events:
                print(f"  - [{e.id}] Node: {e.node}")

if __name__ == "__main__":
    asyncio.run(verify_audit())
