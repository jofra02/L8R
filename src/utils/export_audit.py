from src.core.database import async_session_factory
from src.core.orm import AgentRunORM, AgentEventORM
from sqlalchemy import select, desc
import asyncio
import json
import logging
from datetime import datetime

# Helper for JSON serialization of datetime
def json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError (f"Type {type(obj)} not serializable")

async def export_audit():
    print("--- Exporting Audit Logs to JSON ---")
    
    async with async_session_factory() as session:
        # Fetch all runs
        stmt = select(AgentRunORM).order_by(desc(AgentRunORM.started_at))
        result = await session.execute(stmt)
        runs = result.scalars().all()
        
        export_data = []
        
        for run in runs:
            run_data = {
                "run_id": run.id,
                "ticket_id": run.ticket_id,
                "status": run.status,
                "started_at": run.started_at,
                "events": []
            }
            
            # Fetch events for this run
            stmt_events = select(AgentEventORM).where(AgentEventORM.run_id == run.id).order_by(AgentEventORM.id)
            res_events = await session.execute(stmt_events)
            events = res_events.scalars().all()
            
            for e in events:
                run_data["events"].append({
                    "seq": e.id, # Using ID as sequence proxy
                    "node": e.node,
                    "input": e.input_json,
                    "output": e.output_json
                })
            
            export_data.append(run_data)
            
        # Write to file
        filename = "audit_logs.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, default=json_serial)
            
        print(f"SUCCESS: Exported {len(runs)} runs to '{filename}'")

if __name__ == "__main__":
    asyncio.run(export_audit())
