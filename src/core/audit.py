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
    
    async def create_run(self, ticket_id: str, trace_id: str) -> str:
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
                    state_json={}, # Initial snapshot could be passed here
                    customer_id="global" # Placeholder, should be updated or passed
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

    async def complete_run(self, run_id: str, status: str = "completed"):
        """Mark run as finished."""
        try:
            async with async_session_factory() as session:
                stmt = (
                    update(AgentRunORM)
                    .where(AgentRunORM.id == run_id)
                    .values(
                        status=status,
                        ended_at=datetime.utcnow()
                    )
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.error(f"Audit: Failed to complete run: {e}")

    async def log_event(self, run_id: str, node: str, input_state: Dict[str, Any], output_state: Dict[str, Any]):
        """
        Log a single step (Node Execution).
        """
        try:
            # We assume sequential calls, but for async safety we might settle for approximate sequence
            # or rely on timestamp. 
            async with async_session_factory() as session:
                event = AgentEventORM(
                    run_id=run_id,
                    customer_id=input_state.get("customer_id", "unknown"),
                    node=node,
                    seq=0, # TODO: Track sequence info in Meta if strict ordering needed
                    input_json=self._sanitize(input_state),
                    output_json=self._sanitize(output_state)
                )
                session.add(event)
                await session.commit()
                # logger.debug(f"Audit: Logged event for {node}")
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
            
        # Handle non-serializable objects (like datetime) strictly if needed, 
        # but SQLAlchemy/JSON usually handles basics. 
        # If we see weird types, we might need str() conversion.
        if isinstance(data, datetime):
            return data.isoformat()
            
        return data
