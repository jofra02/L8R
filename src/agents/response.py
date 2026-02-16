from typing import Any, Dict
from src.core.models import GlobalState, HandoffPackage
import logging

logger = logging.getLogger(__name__)

async def response_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Formats final response and handoff.
    """
    ticket = state["ticket"]
    plan = state.get("plan")
    hypotheses = state.get("hypotheses", [])
    evidence = state.get("evidence_refs", [])
    
    logger.info("Response Agent: Formatting final answer.")
    
    # Construct Summary
    leading_hypothesis = hypotheses[0].summary if hypotheses else "Investigation inconclusive"
    plan_steps = len(plan.diagnosis_steps) if plan else 0
    evidence_count = len(evidence)
    
    summary = (
        f"**Analysis for Ticket {ticket.id}**\n\n"
        f"**Leading Hypothesis:** {leading_hypothesis}\n\n"
        f"**Evidence Collected:** {evidence_count} items analyzed.\n"
        f"**Proposed Plan:** {plan_steps} diagnosis steps ready for review.\n"
    )
    
    # Construct Handoff
    handoff = HandoffPackage(
        case_file_artifacts=[e.storage_ref for e in evidence],
        recommended_escalation={"team": "L2_Ops", "reason": "Requires manual verification"}
    )
    
    return {
        "final_answer": summary,
        "handoff": handoff
    }
