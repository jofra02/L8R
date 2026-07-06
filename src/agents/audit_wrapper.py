"""Audit + Langfuse observability wrapper for LangGraph agent nodes.

Extracted from agent_graph.py so that agent_graph_v2.py can reuse it
without transitively importing every legacy agent.
"""

from src.core.models import GlobalState
from src.core.audit import AuditService
from src.core.langfuse_integration import langfuse_manager, get_current_trace, set_current_span
from typing import Dict, Any


def audit_node(node_func, node_name: str):
    """Wraps a node function to log execution events and create Langfuse spans."""

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
            await AuditService().log_event(run_id, node_name, state, {"error": str(e)})
            langfuse_manager.end_span(span, level="ERROR", status_message=str(e))
            raise e

        # Close Langfuse span on success
        langfuse_manager.end_span(span)

        # Audit Log
        if run_id:
            await AuditService().log_event(run_id, node_name, state, result)

        return result
    return wrapped
