from typing import List, Dict, Any
from src.core.interfaces import VectorStoreInterface
from src.core.models import ResolvedTicket, Ticket
import logging

logger = logging.getLogger(__name__)

class CaseRetriever:
    """
    Service to retrieve relevant past cases (CBR) to aid planning.
    """
    def __init__(self, vector_store: VectorStoreInterface):
        self.vector_store = vector_store
        
    async def retrieve_similar_cases(self, ticket: Ticket, limit: int = 3) -> List[ResolvedTicket]:
        """
        Retrieve similar resolved tickets from valid sources.
        """
        logger.info(f"Retriever: Searching for cases similar to: {ticket.text[:50]}...")
        
        # 1. Fetch more candidates than needed to allow for post-filtering/sorting
        fetch_limit = limit * 2
        payloads = await self.vector_store.find_similar_cases(ticket.text, limit=fetch_limit)
        
        # 2. Convert & Filter
        cases = []
        for p in payloads:
            try:
                case = ResolvedTicket(**p)
                
                # Double-check exclusion (though Indexer shouldn't have saved them)
                if case.resolution_status == "unresolved":
                    continue
                    
                cases.append(case)
            except Exception as e:
                logger.error(f"Retriever: Failed to parse retrieved case: {e}")
        
        # 3. Weight/Sort
        # Sort by score (descending) -> Priority to "resolved" (10) over "workaround" (5)
        # Note: Vector Similarity is arguably more important, but user requested explicit weighting.
        # We can combine them if we had the vector score exposed here. 
        # For now, we assume Vector Search gave us "Relevant" items, and we prioritize "Quality" among them.
        cases.sort(key=lambda x: x.score, reverse=True)
        
        # 4. Trim to final limit
        final_cases = cases[:limit]
        
        logger.info(f"Retriever: Found {len(final_cases)} relevant cases after weighting.")
        return final_cases

    def format_cases_for_context(self, cases: List[ResolvedTicket]) -> str:
        """
        Format retrieved cases into a string prompt context.
        """
        if not cases:
            return "No similar past cases found."
            
        context_parts = ["### Relevant Past Cases (Case-Based Reasoning):"]
        for i, case in enumerate(cases, 1):
            context_parts.append(f"Case #{i} (ID: {case.ticket_id}):")
            context_parts.append(f"  - Problem: {case.problem_summary}")
            context_parts.append(f"  - Resolution: {case.resolution_summary}")
            context_parts.append(f"  - Root Cause: {case.root_cause}")
            context_parts.append(f"  - Steps Taken: {case.steps_taken}")
            context_parts.append("---")
            
        return "\n".join(context_parts)
