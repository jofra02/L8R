from typing import Any, Dict, Literal
from src.core.models import GlobalState
import logging

logger = logging.getLogger(__name__)

from src.config import settings

MAX_ITERATIONS = 8 if settings.TEST_MODE_FAST else 15

async def supervisor_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Updates meta-state and logs progress.
    """
    iteration = state.get("meta", {}).get("iterations", 0) + 1
    logger.info(f"Supervisor: Iteration {iteration}")
    
    return {
        "meta": {
            **state.get("meta", {}),
            "iterations": iteration
        }
    }

def supervisor_router(state: GlobalState) -> Literal[
    "context_agent", "classifier_agent", "mapper_agent",
    "evidence_collector", "investigator_agent", "enricher_agent",
    "hypothesis_agent", "planner_agent", "response_agent", "end"
]:
    """
    Conditional Edge Logic.
    Decides the next node based on state.
    """
    # 0. Safety Break
    if state.get("meta", {}).get("iterations", 0) >= MAX_ITERATIONS:
        logger.warning("Max iterations reached. Forcing exit.")
        return "response_agent"

    # 1. Context Check (First run or if missing)
    if not state.get("client_context"):
        return "context_agent"
        
    # 2. Classification Check
    if not state.get("classification") or not state.get("classification").domains:
        return "classifier_agent"
        
    # 3. Component Mapping Check (if applicable)
    if not state.get("components"):
        # Could skipped based on classification, but for now we run it
        return "mapper_agent" # Assuming the graph has this name
        
    # 4. Evidence Collection (The Loop)
    # If missing info is blocking, go to collector
    # Or if confidence is low.
    # Simplified Logic: if no evidence refs, collect.
    if not state.get("evidence_refs"):
        return "evidence_collector"
        
    # 5. Active Diagnosis Loop (Hypothesis Verification)
    hypotheses = state.get("hypotheses", [])
    if hypotheses:
        # Sort by rank
        sorted_hypotheses = sorted(hypotheses, key=lambda x: x.rank)
        
        # A. If we have a VERIFIED hypothesis, we are done with investigation.
        verified_hypotheses = [h for h in sorted_hypotheses if h.status == "verified"]
        if verified_hypotheses:
            logger.info(f"Supervisor: Hypothesis {verified_hypotheses[0].id} is verified. Moving to planning.")
            return "planner_agent" # Explicitly go to planner
            
        # B. If we have PROPOSED hypotheses, verify the best one.
        proposed_hypotheses = [h for h in sorted_hypotheses if h.status == "proposed"]
        if proposed_hypotheses:
            top_hypothesis = proposed_hypotheses[0]
            logger.info(f"Supervisor: Routing to Investigator for hypothesis: {top_hypothesis.id}")
            return "investigator_agent"
            
        # C. If all are rejected or verifying (shouldn't hang in verifying), we might be done or need new hypotheses.
        # If Hypothesis Agent is doing its job, we shouldn't get stuck in 'verifying' without moving state.
        # Fallthrough to Planning (which will likely conclude inconclusive) or Response.


    # 6. Planning
    if not state.get("plan"):
        return "planner_agent"

    # 7. Quality Control & Final Response
    # Check if we have a solid conclusion before exiting
    iterations = state.get("meta", {}).get("iterations", 0)
    
    # Define "Success": Verified Hypothesis AND Plan
    has_verified = any(h.status == "verified" for h in hypotheses)
    has_plan = bool(state.get("plan") and (state.get("plan").diagnosis_steps or state.get("plan").proposed_changes))
    
    # Check for blocking requirements (Human-in-the-Loop)
    pending_reqs = state.get("pending_requirements", [])
    if pending_reqs:
        logger.info(f"Supervisor: Blocking Requirements detected ({len(pending_reqs)}). Routing to Response for User Input.")
        return "response_agent"

    if iterations < MAX_ITERATIONS:
        if not has_verified:
            logger.info("Supervisor: No verified hypothesis yet. Looping back to planner/investigator.")
            # If we have proposals OR verifying, force investigator
            if any(h.status in ["proposed", "verifying"] for h in hypotheses):
                return "investigator_agent"
            return "planner_agent"
            
    # If max iterations reached OR we have success, go to Response
    return "response_agent"
