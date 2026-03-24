"""Shared topology graph utilities."""

from typing import List, Tuple
from src.core.models import ClientContext, TopologyNode, TopologyEdge


def seed_topology_from_context(context: ClientContext) -> Tuple[List[TopologyNode], List[TopologyEdge]]:
    """Convert inventory components to TopologyNodes and dependencies to TopologyEdges."""
    nodes: List[TopologyNode] = []
    edges: List[TopologyEdge] = []

    for comp in context.inventory:
        nodes.append(TopologyNode(
            id=comp.id,
            node_type=comp.role,
            label=comp.ref,
            metadata=comp.metadata,
            evidence_ref="inventory",
        ))

    for dep in context.dependencies:
        edges.append(TopologyEdge(
            source_id=dep.source_id,
            target_id=dep.target_id,
            relation=dep.relation,
            direction="uni",
            metadata=dep.metadata,
            confidence=1.0,
            evidence_ref="inventory",
        ))

    return nodes, edges
