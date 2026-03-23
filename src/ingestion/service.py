from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core.models import Ticket, GlobalState
from src.core.orm import TicketORM, AgentRunORM, PlatformTenant
from src.ingestion.normalizers.generic import GenericNormalizer
from src.core.audit import AuditService
from src.agent_graph import app
from langchain_core.messages import HumanMessage
from typing import Dict, Any, Type, Tuple, Optional, List
from src.core.langfuse_integration import langfuse_manager, set_current_trace
from src.core import task_registry
import asyncio
import logging
import uuid

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
        run_id = await self.audit.create_run(ticket.id, trace_id, customer_id)
        
        logger.info(f"Ticket {ticket.id} persisted. Run ID {run_id} created.")

        return ticket, run_id

    async def run_pipeline_background(self, ticket: Ticket, run_id: str, customer_id: str):
        """Background task to execute the LangGraph workflow."""
        logger.info(f"Background execution started for Run {run_id} (Ticket {ticket.id}, mode={ticket.mode})")
        
        # Create Langfuse root trace for this pipeline execution
        trace = langfuse_manager.create_trace(
            run_id=run_id, ticket_id=ticket.id,
            customer_id=customer_id, thread_id=f"thread_{ticket.id}",
        )
        if trace:
            set_current_trace(trace)

        initial_state = {
            "ticket": ticket,
            "customer_id": customer_id,
            "messages": [HumanMessage(content=ticket.text)],
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
            "final_report": "",
            "final_answer": "",
            "handoff": None,
            "pending_requirements": [],
            "_executed_tool_signatures": [],
            "structured_facts": [],
            "open_questions": [],
            "fulfillment_goals": [],
            "case_status": "new",
            "meta": {
                "iterations": 0,
                "run_id": run_id,
                "trace_id": run_id
            }
        }
        
        try:
            final_state = await app.ainvoke(
                initial_state,
                config={"configurable": {"thread_id": f"thread_{ticket.id}"}}
            )

            # Save final state back to the run
            try:
                serializable_state = self.audit._sanitize(final_state)
            except Exception as e:
                logger.error(f"Failed to sanitize final state: {e}")
                serializable_state = {"error": "Failed to serialize state", "final_answer": str(final_state.get('final_answer', ''))}

            await self.audit.update_run_context(run_id, customer_id, serializable_state)

            # Populate denormalized summary columns
            final_answer = str(final_state.get("final_answer") or "")
            hypothesis_count = len(final_state.get("hypotheses") or [])
            await self.audit.complete_run(
                run_id, "completed",
                final_answer=final_answer,
                hypothesis_count=hypothesis_count,
            )
            logger.info(f"Background execution completed for Run {run_id} (Ticket {ticket.id})")

        except asyncio.CancelledError:
            logger.info(f"Run {run_id} (Ticket {ticket.id}) was cancelled by user.")
            await self.audit.complete_run(run_id, "cancelled")

        except Exception as e:
            logger.error(f"Background execution failed for Run {run_id}: {e}")
            await self.audit.complete_run(run_id, "failed")
        finally:
            task_registry.unregister(run_id)
            langfuse_manager.flush()

    async def get_job_status(self, job_id: str, customer_id: str = None) -> Optional[Dict[str, Any]]:
        """Fetch the status of an agent run (tenant-scoped)."""
        conditions = [AgentRunORM.id == job_id]
        if customer_id:
            conditions.append(AgentRunORM.customer_id == customer_id)
        stmt = select(AgentRunORM).where(*conditions)
        result = await self.session.execute(stmt)
        run = result.scalar_one_or_none()
        if not run:
            return None
        return {"job_id": run.id, "status": run.status, "ticket_id": run.ticket_id, "customer_id": run.customer_id}
        
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

    async def get_ticket_report(self, ticket_id: str, customer_id: str = None) -> Optional[Dict[str, Any]]:
        """Fetch the final report for a ticket's latest run (tenant-scoped)."""
        conditions = [AgentRunORM.ticket_id == ticket_id]
        if customer_id:
            conditions.append(AgentRunORM.customer_id == customer_id)
        stmt = select(AgentRunORM).where(*conditions).order_by(AgentRunORM.started_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        run = result.scalar_one_or_none()
        
        if not run:
            return None
            
        final_answer = run.state_json.get("final_answer", "") if run.state_json else ""
        return {"ticket_id": ticket_id, "job_id": run.id, "status": run.status, "report": final_answer}
