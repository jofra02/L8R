from typing import Any, Dict, List
from src.core.models import GlobalState, ClientContext, TopologyNode, TopologyEdge
from src.core.context_store import ContextStore
from src.core.database import async_session_factory
import logging

logger = logging.getLogger(__name__)

async def context_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Fetches Client Context.
    Seeds topology graph from inventory dependencies.
    """
    customer_id = state.get("customer_id")
    if not customer_id:
        logger.error("No customer_id in state.")
        return {"missing_info": ["customer_id"]}

    logger.info(f"Context Agent: Fetching context for {customer_id}")
    
    async with async_session_factory() as session:
        store = ContextStore(session)
        context = await store.get_active_context(customer_id)
        
        if context:
            logger.info(f"Context found: {context.version}")
            result: Dict[str, Any] = {"client_context": context}
            
            # Seed topology from inventory + dependencies
            topo_nodes, topo_edges = _seed_topology_from_context(context)
            if topo_nodes:
                result["topology_nodes"] = topo_nodes
                logger.info(f"Seeded {len(topo_nodes)} topology nodes from inventory")
            if topo_edges:
                result["topology_edges"] = topo_edges
                logger.info(f"Seeded {len(topo_edges)} topology edges from dependencies")
            
            return result
        else:
            logger.warning("Context not found.")
            default_context = ClientContext(
                customer_id=customer_id, 
                version="v0.0",
                inventory=[],
                baselines=[],
                dependencies=[]
            )
            return {"client_context": default_context, "missing_info": ["client_context_not_found"]}


def _seed_topology_from_context(context: ClientContext) -> tuple:
    """Convert inventory components to TopologyNodes and dependencies to TopologyEdges."""
    nodes: List[TopologyNode] = []
    edges: List[TopologyEdge] = []
    
    # Inventory → Nodes
    for comp in context.inventory:
        nodes.append(TopologyNode(
            id=comp.id,
            node_type=comp.role,
            label=comp.ref,
            metadata=comp.metadata,
            evidence_ref="inventory",
        ))
    
    # Dependencies → Edges (pre-known relationships)
    for dep in context.dependencies:
        edges.append(TopologyEdge(
            source_id=dep.source_id,
            target_id=dep.target_id,
            relation=dep.relation,
            direction="uni",
            metadata=dep.metadata,
            confidence=1.0,  # Known from inventory = high confidence
            evidence_ref="inventory",
        ))
    
    return nodes, edges
