from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from src.core.database import async_session_factory
from src.core.orm import AgentRunORM, AgentEventORM, ToolCallAuditORM
from datetime import datetime
import uuid
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class AuditService:
    """
    Service for structural logging of Agent execution (The "Bitacora").
    """
    _seq_counters: Dict[str, int] = {}  # run_id -> next seq

    async def create_run(self, ticket_id: str, trace_id: str, customer_id: str) -> str:
        """
        Start a new execution run.
        Returns: run_id (UUID string)
        """
        run_id = str(uuid.uuid4())
        
        try:
            async with async_session_factory() as session:
                run = AgentRunORM(
                    id=run_id,
                    ticket_id=ticket_id,
                    trace_id=trace_id,
                    status="running",
                    state_json={},
                    customer_id=customer_id
                )
                session.add(run)
                await session.commit()
                logger.info(f"Audit: Started Run {run_id} for Ticket {ticket_id}")
                return run_id
        except Exception as e:
            logger.error(f"Audit: Failed to create run: {e}")
            return run_id # Return ID anyway so flow continues (logging checks existence? or fails silently)

    async def update_run_context(self, run_id: str, customer_id: str, state_snapshot: Dict[str, Any]):
        """
        Update the run with customer context and initial state once known.
        """
        try:
            async with async_session_factory() as session:
                stmt = (
                    update(AgentRunORM)
                    .where(AgentRunORM.id == run_id)
                    .values(
                        customer_id=customer_id, 
                        state_json=state_snapshot
                    )
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.error(f"Audit: Failed to update run context: {e}")

    async def complete_run(
        self,
        run_id: str,
        status: str = "completed",
        final_answer: Optional[str] = None,
        hypothesis_count: Optional[int] = None,
        decision: Optional[str] = None,
    ):
        """Mark run as finished, optionally storing denormalized summary fields."""
        try:
            async with async_session_factory() as session:
                values: Dict[str, Any] = {"status": status, "ended_at": datetime.utcnow()}
                if final_answer is not None:
                    values["final_answer"] = final_answer
                if hypothesis_count is not None:
                    values["hypothesis_count"] = hypothesis_count
                if decision is not None:
                    values["decision"] = decision
                stmt = update(AgentRunORM).where(AgentRunORM.id == run_id).values(**values)
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.error(f"Audit: Failed to complete run: {e}")

    def _next_seq(self, run_id: str) -> int:
        """Return and increment the sequence counter for a run."""
        seq = self._seq_counters.get(run_id, 0) + 1
        self._seq_counters[run_id] = seq
        return seq

    async def log_event(self, run_id: str, node: str, input_state: Dict[str, Any], output_state: Dict[str, Any]):
        """
        Log a single step (Node Execution).
        """
        try:
            seq = self._next_seq(run_id)
            async with async_session_factory() as session:
                event = AgentEventORM(
                    run_id=run_id,
                    customer_id=input_state.get("customer_id", "unknown"),
                    node=node,
                    seq=seq,
                    input_json=self._sanitize(input_state),
                    output_json=self._sanitize(output_state)
                )
                session.add(event)
                await session.commit()
        except Exception as e:
            logger.error(f"Audit: Failed to log event for {node}: {e}")

    def _sanitize(self, data: Any) -> Any:
        # Recursive sanitization for Pydantic models and lists
        if hasattr(data, "model_dump"):
            return self._sanitize(data.model_dump())
        if hasattr(data, "dict"):
            return self._sanitize(data.dict())
        
        if isinstance(data, dict):
             # Exclude heavy objects or PII if needed
             return {k: self._sanitize(v) for k, v in data.items() if k != "client_context"} 
        
        if isinstance(data, list):
            return [self._sanitize(item) for item in data]

        if isinstance(data, (set, frozenset)):
            return [self._sanitize(item) for item in data]

        if isinstance(data, tuple):
            return [self._sanitize(item) for item in data]

        if isinstance(data, datetime):
            return data.isoformat()

        return data
