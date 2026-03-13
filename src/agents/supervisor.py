from typing import Any, Dict, Literal
from src.core.models import GlobalState
import logging

logger = logging.getLogger(__name__)

from src.config import settings

MAX_ITERATIONS = 8 if settings.TEST_MODE_FAST else 15

async def supervisor_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Updates meta-state and logs progress.
    Sets case_status to 'new' on first iteration if not set.
    """
    iteration = state.get("meta", {}).get("iterations", 0) + 1
    logger.info(f"Supervisor: Iteration {iteration}")

    result: Dict[str, Any] = {
        "meta": {
            **state.get("meta", {}),
            "iterations": iteration
        }
    }

    # Initialize case_status on first pass
    if not state.get("case_status"):
        result["case_status"] = "new"

    return result

def supervisor_router(state: GlobalState) -> Literal[
    "context_agent", "classifier_agent", "mapper_agent",
    "evidence_collector", "investigator_agent", "enricher_agent",
    "hypothesis_agent", "investigation_planner", "goal_decomposer",
    "scoring_agent", "planner_agent", "response_agent", "end"
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

    # 5b. Fulfillment path: change/request tickets go to goal decomposer (P6)
    ticket = state.get("ticket")
    ticket_mode = ticket.mode if ticket else "incident"
    if ticket_mode == "change" and not state.get("fulfillment_goals") and not state.get("hypotheses"):
        logger.info("Supervisor: Change ticket → goal decomposer.")
        return "goal_decomposer"

    # 6. SCORING-DRIVEN DECISION GATE
    scoring = state.get("scoring")
    if scoring:
        # Handle both ScoringResult object and dict (from JSON resume)
        decision = scoring.get("decision") if isinstance(scoring, dict) else scoring.decision
        confidence = scoring.get("confidence", 0) if isinstance(scoring, dict) else scoring.confidence
        risk_score = scoring.get("risk_score", 0) if isinstance(scoring, dict) else scoring.risk_score

        if decision == "proceed_to_plan":
            if state.get("plan"):
                # Plan already exists → go to response
                logger.info("Supervisor: Plan ready, routing to response.")
                return "response_agent"
            logger.info(f"Supervisor: Scoring gate → proceed_to_plan (confidence={confidence:.0%})")
            return "planner_agent"

        elif decision == "needs_more_evidence":
            # Route to investigation planner if no open questions, then investigator
            hypotheses = state.get("hypotheses", [])
            active = [h for h in hypotheses if h.status in ("proposed", "verifying")]
            if active:
                # Check if we need to (re)plan the investigation
                open_questions = state.get("open_questions", [])
                open_count = len([q for q in open_questions if q.status == "open"])
                if open_count == 0:
                    logger.info("Supervisor: Scoring gate → needs_more_evidence → investigation_planner")
                    return "investigation_planner"
                logger.info(f"Supervisor: Scoring gate → needs_more_evidence → investigator ({open_count} open questions)")
                return "investigator_agent"
            else:
                logger.info(f"Supervisor: Scoring gate → needs_more_evidence → evidence_collector")
                return "evidence_collector"

        elif decision == "escalate_to_human":
            logger.info(f"Supervisor: Scoring gate → escalate_to_human (risk={risk_score})")
            return "response_agent"

    # 7. Fallback: Pre-scoring routing (first iteration, before scoring exists)
    hypotheses = state.get("hypotheses", [])
    if hypotheses:
        # If we have a verified hypothesis but no scoring yet, go to planner
        verified = [h for h in hypotheses if h.status == "verified"]
        if verified:
            return "planner_agent"

        # If proposed/verifying, go to investigation planner first
        active = [h for h in hypotheses if h.status in ("proposed", "verifying")]
        if active:
            open_questions = state.get("open_questions", [])
            open_count = len([q for q in open_questions if q.status == "open"])
            if open_count == 0:
                return "investigation_planner"
            return "investigator_agent"

    # 8. No hypotheses yet but evidence exists → run enricher→hypothesis→scoring
    if not state.get("hypotheses"):
        return "enricher_agent"

    # 9. Default: go to response
    return "response_agent"

