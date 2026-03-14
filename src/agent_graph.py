from langgraph.graph import StateGraph, END
from src.core.models import GlobalState
from src.agents.supervisor import supervisor_agent_node, supervisor_router
from src.agents.context_agent import context_agent_node
from src.agents.classifier import classifier_agent_node
from src.agents.mapper import mapper_agent_node
from src.agents.evidence_collector import evidence_collector_node
from src.agents.enricher import enricher_agent_node
from src.agents.hypothesis import hypothesis_agent_node
from src.agents.investigation_planner import investigation_planner_node
from src.agents.goal_decomposer import goal_decomposer_node
from src.agents.planner import resolution_planner_agent_node
from src.agents.response import response_agent_node
from src.agents.investigator import investigator_agent_node
from src.agents.scoring import scoring_agent_node
from typing import Dict, Any

# Initialize Graph
workflow = StateGraph(GlobalState)

# --- Audit Wrapper ---
from src.core.audit import AuditService
import asyncio

from src.core.langfuse_integration import langfuse_manager, get_current_trace, set_current_span

def audit_node(node_func, node_name: str):
    """
    Wraps a node function to log execution events and create Langfuse spans.
    """
    async def wrapped(state: GlobalState) -> Dict[str, Any]:
        run_id = state.get("meta", {}).get("run_id")
        customer_id = state.get("customer_id")

        # Create Langfuse span for this agent node
        trace = get_current_trace()
        span = None
        if trace:
            span = langfuse_manager.create_span(
                parent=trace, name=f"agent:{node_name}",
                metadata={"run_id": run_id, "customer_id": customer_id,
                          "iteration": state.get("meta", {}).get("iterations", 0)},
            )
            set_current_span(span)

        # Execute the actual node
        try:
            result = await node_func(state)
        except Exception as e:
            # Log failure
            await AuditService().log_event(run_id, node_name, state, {"error": str(e)})
            if span:
                try:
                    span.end(status_message=str(e), level="ERROR")
                except Exception:
                    pass
            raise e

        # Close Langfuse span on success
        if span:
            try:
                span.end(status_message="ok")
            except Exception:
                pass

        # Audit Log (Fire and Forget)
        if run_id:
            # We use ensure_future to not block the main flow,
            # OR await it if we want strict consistency.
            # For now, let's await to be safe against event loop closing.
            await AuditService().log_event(run_id, node_name, state, result)

        return result
    return wrapped

# 1. Add Nodes (Wrapped)
workflow.add_node("supervisor", audit_node(supervisor_agent_node, "supervisor"))
workflow.add_node("context_agent", audit_node(context_agent_node, "context_agent"))
workflow.add_node("classifier_agent", audit_node(classifier_agent_node, "classifier_agent"))
workflow.add_node("mapper_agent", audit_node(mapper_agent_node, "mapper_agent"))
workflow.add_node("evidence_collector", audit_node(evidence_collector_node, "evidence_collector"))
workflow.add_node("investigator_agent", audit_node(investigator_agent_node, "investigator_agent"))
workflow.add_node("enricher_agent", audit_node(enricher_agent_node, "enricher_agent"))
workflow.add_node("hypothesis_agent", audit_node(hypothesis_agent_node, "hypothesis_agent"))
workflow.add_node("investigation_planner", audit_node(investigation_planner_node, "investigation_planner"))
workflow.add_node("goal_decomposer", audit_node(goal_decomposer_node, "goal_decomposer"))
workflow.add_node("scoring_agent", audit_node(scoring_agent_node, "scoring_agent"))
workflow.add_node("planner_agent", audit_node(resolution_planner_agent_node, "planner_agent"))
workflow.add_node("response_agent", audit_node(response_agent_node, "response_agent"))

# 2. Define Edges (Supervisor Driven)
# The supervisor determines the next step based on state
workflow.set_entry_point("supervisor")

workflow.add_conditional_edges(
    "supervisor",
    supervisor_router,
    {
        "context_agent": "context_agent",
        "classifier_agent": "classifier_agent",
        "mapper_agent": "mapper_agent",
        "evidence_collector": "evidence_collector",
        "investigator_agent": "investigator_agent",
        "enricher_agent": "enricher_agent",
        "hypothesis_agent": "hypothesis_agent",
        "investigation_planner": "investigation_planner",
        "goal_decomposer": "goal_decomposer",
        "planner_agent": "planner_agent",
        "response_agent": "response_agent",
        "end": END
    }
)

# 3. Return Edges to Supervisor
# After each specialist finishes, return to supervisor to update state/iteration and route again
workflow.add_edge("context_agent", "supervisor")
workflow.add_edge("classifier_agent", "supervisor")
workflow.add_edge("mapper_agent", "supervisor")
workflow.add_edge("evidence_collector", "enricher_agent")    # Sub-chain: Collect -> Enrich
workflow.add_edge("investigator_agent", "enricher_agent")    # Sub-chain: Investigate -> Enrich
workflow.add_edge("enricher_agent", "hypothesis_agent")      # Sub-chain: Enrich -> Hypothesis
workflow.add_edge("hypothesis_agent", "scoring_agent")       # Sub-chain: Hypothesis -> Scoring
workflow.add_edge("scoring_agent", "supervisor")             # Scoring gates -> Supervisor decides next
workflow.add_edge("investigation_planner", "supervisor")     # Investigation plan -> Supervisor routes to investigator
workflow.add_edge("goal_decomposer", "supervisor")           # Goal decomposition -> Supervisor routes next
workflow.add_edge("planner_agent", "supervisor")
workflow.add_edge("response_agent", END)

# 4. Compile
app = workflow.compile()
