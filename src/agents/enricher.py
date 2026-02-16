from typing import Any, Dict
from src.core.models import GlobalState
import logging

logger = logging.getLogger(__name__)

async def enricher_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Enriches facts with extra context.
    """
    evidence_refs = state.get("evidence_refs", [])
    facts = state.get("facts", {})
    
    logger.info(f"Enricher: Processing {len(evidence_refs)} evidence items.")
    
    # Simple enrichment logic for MVP
    enriched_facts = facts.copy()
    
    for ref in evidence_refs:
        # Example: if tool was 'status', extraction some key metrics
        if "status" in ref.tool_name:
            enriched_facts[f"status_{ref.id}"] = "analyzed"
            
    return {"facts": enriched_facts}
