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
    "hypothesis_agent", "scoring_agent", "planner_agent", "response_agent", "end"
]:
    """
    Conditional Edge Logic.
    Decides the next node based on state. Uses scoring.decision when available.
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
        
    # 3. Component Mapping Check
    if not state.get("components"):
        return "mapper_agent"
        
    # 4. Initial Evidence Collection (first pass)
    if not state.get("evidence_refs"):
        return "evidence_collector"
    
    # 5. Check for blocking requirements (Human-in-the-Loop)
    pending_reqs = state.get("pending_requirements", [])
    if pending_reqs:
        logger.info(f"Supervisor: Blocking Requirements detected ({len(pending_reqs)}). Routing to Response for User Input.")
        return "response_agent"
    
    # 6. SCORING-DRIVEN DECISION GATE
    scoring = state.get("scoring")
    if scoring:
        decision = scoring.decision
        
        if decision == "proceed_to_plan":
            if state.get("plan"):
                # Plan already exists → go to response
                logger.info("Supervisor: Plan ready, routing to response.")
                return "response_agent"
            logger.info(f"Supervisor: Scoring gate → proceed_to_plan (confidence={scoring.confidence:.0%})")
            return "planner_agent"
        
        elif decision == "needs_more_evidence":
            # Route to investigator if there are active hypotheses, otherwise evidence collector
            hypotheses = state.get("hypotheses", [])
            active = [h for h in hypotheses if h.status in ("proposed", "verifying")]
            if active:
                logger.info(f"Supervisor: Scoring gate → needs_more_evidence → investigator")
                return "investigator_agent"
            else:
                logger.info(f"Supervisor: Scoring gate → needs_more_evidence → evidence_collector")
                return "evidence_collector"
        
        elif decision == "escalate_to_human":
            logger.info(f"Supervisor: Scoring gate → escalate_to_human (risk={scoring.risk_score})")
            return "response_agent"
    
    # 7. Fallback: Pre-scoring routing (first iteration, before scoring exists)
    hypotheses = state.get("hypotheses", [])
    if hypotheses:
        # If we have a verified hypothesis but no scoring yet, go to planner
        verified = [h for h in hypotheses if h.status == "verified"]
        if verified:
            return "planner_agent"
        
        # If proposed/verifying, go to investigator
        active = [h for h in hypotheses if h.status in ("proposed", "verifying")]
        if active:
            return "investigator_agent"
    
    # 8. No hypotheses yet but evidence exists → fallback to planner
    if not state.get("plan"):
        return "planner_agent"
    
    # 9. Default: go to response
    return "response_agent"

