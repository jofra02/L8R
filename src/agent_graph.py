from langgraph.graph import StateGraph, END
from src.core.models import GlobalState
from src.agents.supervisor import supervisor_agent_node, supervisor_router
# from src.agents.context_agent import context_agent_node
# from src.agents.classifier import classifier_agent_node
# from src.agents.mapper import mapper_agent_node
# from src.agents.evidence_collector import evidence_collector_node
# from src.agents.enricher import enricher_agent_node
# from src.agents.hypothesis import hypothesis_agent_node
# from src.agents.planner import planner_agent_node
# from src.agents.response import response_agent_node
# from src.core.database import CheckpointORM # For persistence (future)

# Initialize Graph
workflow = StateGraph(GlobalState)

# 1. Add Nodes
workflow.add_node("supervisor", supervisor_agent_node)
# workflow.add_node("context_agent", context_agent_node)
# workflow.add_node("classifier_agent", classifier_agent_node)
# workflow.add_node("mapper_agent", mapper_agent_node)
# workflow.add_node("evidence_collector", evidence_collector_node)
# workflow.add_node("normalizer_agent", ...) # Skip for MVP or strictly ingress
# workflow.add_node("enricher_agent", enricher_agent_node)
# workflow.add_node("hypothesis_agent", hypothesis_agent_node)
# workflow.add_node("planner_agent", planner_agent_node)
# workflow.add_node("response_agent", response_agent_node)

# 2. Define Edges (Supervisor Driven)
# The supervisor determines the next step based on state
workflow.set_entry_point("supervisor")

workflow.add_conditional_edges(
    "supervisor",
    supervisor_router,
    # {
    #     "context_agent": "context_agent",
    #     "classifier_agent": "classifier_agent",
    #     "mapper_agent": "mapper_agent",
    #     "evidence_collector": "evidence_collector",
    #     "enricher_agent": "enricher_agent", # Router might not explicitly name this, need to check supervisor.py logic
    #     "hypothesis_agent": "hypothesis_agent", # Need to ensure supervisor routes here
    #     "planner_agent": "planner_agent",
    #     "response_agent": "response_agent",
    #     "end": END
    # }
)

# 3. Return Edges to Supervisor
# After each specialist finishes, return to supervisor to update state/iteration and route again
# workflow.add_edge("context_agent", "supervisor")
# workflow.add_edge("classifier_agent", "supervisor")
# workflow.add_edge("mapper_agent", "supervisor")
# workflow.add_edge("evidence_collector", "enricher_agent") # Linear sub-chain: Collect -> Enrich -> Supervisor
# workflow.add_edge("enricher_agent", "hypothesis_agent") # Enrich -> Hypothesis -> Supervisor
# workflow.add_edge("hypothesis_agent", "supervisor")
# workflow.add_edge("planner_agent", "supervisor")
# workflow.add_edge("response_agent", END)

# 4. Compile
app = workflow.compile()
