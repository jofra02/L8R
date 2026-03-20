from typing import List, Dict, Any, Optional
import logging
from datetime import datetime
from src.core.models import Ticket, ResolvedTicket, Plan
from src.core.interfaces import VectorStoreInterface

logger = logging.getLogger(__name__)

class TicketIndexer:
    """
    Handles the conversion of closed tickets into Retrievable Knowledge (CBR).
    Implements Weighting & Exclusion logic.
    """
    
    def __init__(self, vector_store: VectorStoreInterface):
        self.vector_store = vector_store

    async def index_resolved_case(self, 
                                ticket: Ticket, 
                                plan: Plan, 
                                final_answer: str,
                                customer_id: str,
                                root_cause: str = "Unknown",
                                resolution_status: str = "resolved"):
        """
        Transforms a closed ticket into a ResolvedTicket and indexes it.
        
        CRITICAL: 
        - If 'unresolved' or no clear solution, DISCARD (do not index).
        - 'resolved' gets standard high score.
        - 'workaround' gets lower score.
        """
        
        # --- 1. Exclusion Logic ---
        if resolution_status == "unresolved":
            logger.info(f"Indexer: Skipping ticket {ticket.id} (Status: Unresolved).")
            return
            
        if not final_answer or len(final_answer) < 10:
             logger.warning(f"Indexer: Skipping ticket {ticket.id} (No clear final answer).")
             return

        # --- 2. Weighting/Scoring ---
        quality_score = 10
        if resolution_status == "workaround":
            quality_score = 5
        
        # --- 3. Construct Payload ---
        try:
            # Extract tools used from plan
            # We want the tools that actually initiated changes or diagnoses
            tools_used = []
            for step in plan.diagnosis_steps + plan.proposed_changes:
                tools_used.append({
                    "tool": step.tool,
                    "args": step.args,
                    "outcome": step.expected_outcome
                })

            resolved_case = ResolvedTicket(
                ticket_id=ticket.id,
                problem_summary=ticket.text,
                resolution_summary=final_answer,
                root_cause=root_cause,
                tools_used=tools_used,
                steps_taken=[s.description for s in plan.proposed_changes],
                customer_id=customer_id,
                resolution_status=resolution_status,
                score=quality_score,
                resolved_at=datetime.now()
            )
            
            # --- 4. Save to Vector Store ---
            await self.vector_store.save_resolved_ticket(resolved_case, customer_id=customer_id)
            
            # --- 5. Consistency Check ---
            # Verify immediately (RAG Telemetry)
            logger.debug(f"Indexer: Verifying consistency for {ticket.id}...")
            found_cases = await self.vector_store.find_similar_cases(ticket.text, customer_id=customer_id, limit=5)
            
            # Note: find_similar_cases returns List[Dict] (payloads)
            is_indexed = False
            for c in found_cases:
                # Check ID. Assuming payload has ticket_id
                if c.get('ticket_id') == ticket.id:
                    is_indexed = True
                    break
            
            if is_indexed:
                 logger.info(f"Indexer: PASS. Ticket {ticket.id} is retrievable (Score: {quality_score}).")
            else:
                 logger.error(f"Indexer: FAIL. Ticket {ticket.id} NOT found immediately after save.")
            
        except Exception as e:
            logger.error(f"Indexer: Failed to index ticket {ticket.id}: {e}")
