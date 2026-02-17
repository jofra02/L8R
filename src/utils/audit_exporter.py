import asyncio
import logging
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.core.database import async_session_factory
from src.core.orm import AgentRunORM, AgentEventORM
import json
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("audit_exporter")

async def export_latest_run_to_md(output_file: str = "audit_report.md"):
    """
    Fetches the most recent agent run and exports it to a readable Markdown file.
    """
    async with async_session_factory() as session:
        # 1. Get Latest Run
        stmt = (
            select(AgentRunORM)
            .order_by(AgentRunORM.started_at.desc())
            .limit(1)
            .options(selectinload(AgentRunORM.ticket))
        )
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        
        if not run:
            logger.error("No runs found in database.")
            return

        logger.info(f"Exporting Run ID: {run.id} (Ticket: {run.ticket_id})")

        # 2. Get Events for Run
        # Ordered by ID since seq is currently 0
        stmt_events = (
            select(AgentEventORM)
            .where(AgentEventORM.run_id == run.id)
            .order_by(AgentEventORM.id.asc())
        )
        events_res = await session.execute(stmt_events)
        events = events_res.scalars().all()
        
        # 3. Build Markdown
        md_lines = []
        md_lines.append(f"# 🛡️ Audit Report: Run {run.id}")
        md_lines.append(f"**Date:** {datetime.now().isoformat()}")
        md_lines.append(f"**Ticket ID:** {run.ticket_id}")
        md_lines.append(f"**Ticket Text:** {run.ticket.text if run.ticket else 'N/A'}")
        md_lines.append(f"**Status:** {run.status}")
        md_lines.append(f"**Trace ID:** {run.trace_id}")
        md_lines.append("\n---")
        
        for i, event in enumerate(events):
            timestamp = event.created_at.strftime("%H:%M:%S") if event.created_at else "Unknown"
            md_lines.append(f"## {i+1}. Node: `{event.node}`")
            md_lines.append(f"_{timestamp}_")
            
            # Input (Collapsible)
            md_lines.append("<details>")
            md_lines.append("<summary>📥 <strong>Input State</strong></summary>")
            md_lines.append("\n```json")
            md_lines.append(json.dumps(event.input_json, indent=2, default=str))
            md_lines.append("```\n")
            md_lines.append("</details>")
            
            # Output (Collapsible)
            md_lines.append("<details>")
            md_lines.append("<summary>📤 <strong>Output (Delta)</strong></summary>")
            md_lines.append("\n```json")
            md_lines.append(json.dumps(event.output_json, indent=2, default=str))
            md_lines.append("```\n")
            md_lines.append("</details>")
            
            md_lines.append("\n---\n")

        # 4. Write File
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        
        logger.info(f"Audit report saved to {os.path.abspath(output_file)}")

if __name__ == "__main__":
    asyncio.run(export_latest_run_to_md())
