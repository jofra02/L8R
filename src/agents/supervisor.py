from typing import Any, Dict, Literal
from src.core.models import GlobalState
import logging

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10

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

def supervisor_router(state: GlobalState) -> Literal["context_agent", "classifier_agent", "evidence_collector", "planner_agent", "response_agent", "end"]:
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
        
    # 5. Planning
    if not state.get("plan"):
        return "planner_agent"
        
    # 6. Final Response
    return "response_agent"
