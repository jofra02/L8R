"""Minimal LangGraph graph for the Engineer single-agent architecture.

One node (engineer) → END. All intelligence lives in the Engineer agent;
the graph provides state management and audit/observability wrapping.
"""

from langgraph.graph import StateGraph, END
from src.core.models import GlobalState
from src.agents.engineer import engineer_agent_node
from src.agent_graph import audit_node  # Reuse existing Langfuse + audit wrapper

workflow = StateGraph(GlobalState)
workflow.add_node("engineer", audit_node(engineer_agent_node, "engineer"))
workflow.set_entry_point("engineer")
workflow.add_edge("engineer", END)

app_v2 = workflow.compile()
