from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core.models import Ticket, GlobalState
from src.core.orm import TicketORM, AgentRunORM, PlatformTenant
from src.ingestion.normalizers.generic import GenericNormalizer
from src.core.audit import AuditService
from src.agent_graph import app
from langchain_core.messages import HumanMessage
from typing import Dict, Any, Type, Tuple, Optional, List
import logging
import uuid
import datetime

logger = logging.getLogger(__name__)

class IngestionService:
    """Service to handle ticket ingestion and persistence."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.normalizer = GenericNormalizer()  # In future, use factory based on source
        self.audit = AuditService()

    async def ingest_webhook(self, source: str, payload: Dict[str, Any], customer_id: str) -> Tuple[str, str, str]:
        """Process a webhook payload and setup the initial execution run."""
        logger.info(f"Ingesting webhook from {source} for customer {customer_id}")
        
        # 1. Normalize
        ticket: Ticket = self.normalizer.normalize(payload, source_id=f"webhook:{source}")
        
        # 2. Persist to DB
        ticket_orm = TicketORM(
            id=ticket.id,
            customer_id=customer_id,
            mode=ticket.mode,
            severity=ticket.severity,
            source=ticket.source,
            text=ticket.text,
            raw_payload=ticket.raw_payload
        )
        
        self.session.add(ticket_orm)
        await self.session.commit()
        
        # 3. Create Audit Run (Job ID)
        trace_id = str(uuid.uuid4())
        run_id = await self.audit.create_run(ticket.id, trace_id)
        
        logger.info(f"Ticket {ticket.id} persisted. Run ID {run_id} created.")
        
        return ticket.id, run_id, ticket.text

    async def run_pipeline_background(self, ticket_id: str, run_id: str, customer_id: str, text: str):
        """Background task to execute the LangGraph workflow."""
        logger.info(f"Background execution started for Run {run_id} (Ticket {ticket_id})")
        
        # We need a ticket object for the state. We'll reconstruct a basic one from params
        mock_ticket = Ticket(
            id=ticket_id,
            mode="incident",
            text=text,
            severity="medium",
            source="webhook",
            timestamps={"created_at": datetime.datetime.now().isoformat()}
        )
        
        initial_state = {
            "ticket": mock_ticket,
            "customer_id": customer_id,
            "messages": [HumanMessage(content=text)],
            "client_context": None,
            "classification": None,
            "components": [],
            "evidence_refs": [],
            "missing_info": [],
            "facts": {},
            "hypotheses": [],
            "plan": None,
            "final_report": "",
            "final_answer": "",
            "handoff": None,
            "pending_requirements": [],
            "meta": {
                "iterations": 0,
                "run_id": run_id,
                "trace_id": "async_trace"
            }
        }
        
        try:
            final_state = await app.ainvoke(
                initial_state,
                config={"configurable": {"thread_id": f"thread_{ticket_id}"}}
            )
            
            # Save final state back to the run
            # Use the robust sanitize method from AuditService to ensure SQLAlchemy/FastAPI can serialize everything
            try:
                serializable_state = self.audit._sanitize(final_state)
            except Exception as e:
                logger.error(f"Failed to sanitize final state: {e}")
                serializable_state = {"error": "Failed to serialize state", "final_answer": str(final_state.get('final_answer', ''))}
            
            logger.info(f"DEBUG: serializable_state keys before save: {list(serializable_state.keys())}")
            
            await self.audit.update_run_context(run_id, customer_id, serializable_state)
            
            # complete_run does not exist yet wait, let me check AuditService
            # Need to patch audit service for complete_run or just update status via query
            await self._mark_run_completed(run_id, "completed")
            logger.info(f"Background execution completed for Run {run_id}")
            
        except Exception as e:
            logger.error(f"Background execution failed for Run {run_id}: {e}")
            await self._mark_run_completed(run_id, "failed")

    async def _mark_run_completed(self, run_id: str, status: str):
         """Helper to mark run completed since AuditService may lack it."""
         from sqlalchemy import update
         from src.core.database import async_session_factory
         async with async_session_factory() as session:
             stmt = update(AgentRunORM).where(AgentRunORM.id == run_id).values(status=status, ended_at=datetime.datetime.now())
             await session.execute(stmt)
             await session.commit()

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the status of an agent run."""
        stmt = select(AgentRunORM).where(AgentRunORM.id == job_id)
        result = await self.session.execute(stmt)
        run = result.scalar_one_or_none()
        if not run:
            return None
        return {"job_id": run.id, "status": run.status, "ticket_id": run.ticket_id}
        
    async def get_tenant_jobs(self, customer_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch recent jobs for a specific tenant."""
        stmt = (
            select(AgentRunORM)
            .join(TicketORM, AgentRunORM.ticket_id == TicketORM.id)
            .where(TicketORM.customer_id == customer_id)
            .order_by(AgentRunORM.started_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        runs = result.scalars().all()
        
        jobs = []
        for run in runs:
            jobs.append({
                "job_id": run.id,
                "ticket_id": run.ticket_id,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "ended_at": run.ended_at.isoformat() if run.ended_at else None,
            })
        return jobs

    async def get_all_tenants(self) -> List[Dict[str, str]]:
        """Fetch all registered tenants."""
        stmt = select(PlatformTenant)
        result = await self.session.execute(stmt)
        tenants = result.scalars().all()
        # Handle the field correctly (PlatformTenant has customer_id as PK)
        return [{"id": t.customer_id, "name": t.name} for t in tenants]

    async def get_ticket_report(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the final report for a ticket's latest run."""
        stmt = select(AgentRunORM).where(AgentRunORM.ticket_id == ticket_id).order_by(AgentRunORM.started_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        run = result.scalar_one_or_none()
        
        if not run:
            return None
            
        final_answer = run.state_json.get("final_answer", "") if run.state_json else ""
        return {"ticket_id": ticket_id, "job_id": run.id, "status": run.status, "report": final_answer}
