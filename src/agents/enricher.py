from typing import Any, Dict, List
from src.core.models import GlobalState, TopologyNode, TopologyEdge, Fact
from src.core.llm import LLMFactory
from datetime import datetime
from langchain_core.messages import SystemMessage, HumanMessage
import logging
import json

logger = logging.getLogger(__name__)

async def enricher_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Enriches facts with extra context by synthesizing evidence.
    Also extracts topology nodes and edges for dependency graph reasoning.
    """
    evidence_refs = state.get("evidence_refs", [])
    facts = state.get("facts", {})
    
    logger.info(f"Enricher: Processing {len(evidence_refs)} evidence items.")
    
    # Identify evidence that hasn't been synthesized into facts yet
    processed_evidence_ids = facts.get("_processed_evidence_ids", [])
    new_evidence = [e for e in evidence_refs if e.id not in processed_evidence_ids]
    
    if not new_evidence:
        logger.info("Enricher: No new evidence to synthesize.")
        meta = state.get("meta", {})
        meta["enricher_skipped"] = True
        return {"meta": meta}

    logger.info(f"Enricher: Synthesizing {len(new_evidence)} new evidence items into facts.")
    llm = LLMFactory.get_model_for_agent("enricher")
    
    enriched_facts = facts.copy()
    structured_facts: List[Fact] = list(state.get("structured_facts", []))

    # Topology accumulators (merge with existing)
    existing_nodes = state.get("topology_nodes", [])
    existing_edges = state.get("topology_edges", [])
    new_nodes: List[TopologyNode] = []
    new_edges: List[TopologyEdge] = []
    
    # Build context for topology: known components
    components = state.get("components", [])
    components_str = ", ".join([f"{c.id} ({c.role})" for c in components]) if components else "none"
    
    for ref in new_evidence:
        # Load raw evidence content
        try:
            with open(ref.storage_ref, "r", encoding="utf-8") as f:
                raw_text = f.read()
                try:
                    raw_content = json.loads(raw_text)
                except json.JSONDecodeError:
                    raw_content = {"raw_text": raw_text}
        except Exception as e:
            logger.warning(f"Enricher: Could not load file {ref.storage_ref}: {e}")
            raw_content = {"summary": ref.summary}
            
        from src.utils.json_compressor import compress_json_payload
        compressed_evidence = compress_json_payload(raw_content)
        evidence_str = json.dumps(compressed_evidence, indent=2)
        
        # ─── Pass 1: Fact Extraction ──────────────────────────────
        fact_prompt = f"""
Extract key technical facts from the following evidence snippet gathered during an IT investigation.

Focus on:
1. **Concrete values**: identifiers, addresses, error codes, statuses, performance metrics (latency, throughput, response times), configuration settings, version numbers, resource utilization, log entries, and any measurable quantities.
2. **MITRE ATT&CK mapping**: If the evidence suggests attack-related behavior, include a "mitre_mapping" key with tactic and technique. Only include if clearly applicable.

Evidence Tool: {ref.tool_name}
Evidence Summary: {ref.summary}
Evidence Content (Compressed):
{evidence_str}

Return ONLY a valid JSON dictionary of key-value pairs.
"""
        
        try:
             response = await llm.ainvoke(
                 [
                     SystemMessage(content="You are a data extraction specialist. Output only valid JSON. Include MITRE ATT&CK mapping only when evidence clearly indicates attack-related behavior."),
                     HumanMessage(content=fact_prompt)
                 ],
                 response_format={"type": "json_object"},
             )
             extracted_json = response.content.strip().replace("```json", "").replace("```", "")
             extracted_facts = json.loads(extracted_json)
             
             for k, v in extracted_facts.items():
                 enriched_facts[k] = v
                 # Also produce structured fact with provenance
                 structured_facts.append(Fact(
                     key=k,
                     value=v,
                     source_evidence_id=ref.id,
                     confidence=1.0,
                     timestamp=datetime.now(),
                 ))

             logger.info(f"Enricher: Extracted {len(extracted_facts)} facts from evidence {ref.id[:8]}")
             
        except Exception as e:
             logger.warning(f"Enricher: Failed to extract facts from {ref.id[:8]}: {e}")
        
        # ─── Pass 2: Topology Extraction ─────────────────────────
        topo_prompt = f"""
Analyze the following evidence and extract **relationships between entities** (devices, services, applications, databases, containers, subnets, APIs, storage, queues, etc.).

Known components: {components_str}

Evidence Tool: {ref.tool_name}
Evidence Summary: {ref.summary}
Evidence Content (Compressed):
{evidence_str}

Extract two things:

1. **nodes**: Entities found in the evidence (any identifiable component, resource, or endpoint).
2. **edges**: Relationships between entities that describe connectivity, dependency, or data flow.

Edge relation types: "connects_to", "depends_on", "serves", "hosts", "routes_to", "calls_api", "queries", "reads_from", "writes_to", "authenticates_via", "publishes_to", "subscribes_to", "replicates_to", "load_balances", "proxies", "mounts", "dns_resolves", "policy_allow", "policy_deny", "nat"

Return ONLY a JSON object:
{{
  "nodes": [
    {{"id": "entity_id", "node_type": "device|service|application|database|container|subnet|interface|host|vm|api|storage|cluster|queue|endpoint|dns_name", "label": "human label"}}
  ],
  "edges": [
    {{"source_id": "entity_a", "target_id": "entity_b", "relation": "connects_to", "direction": "uni|bi", "metadata": {{}}, "confidence": 0.8}}
  ]
}}

If no relationships are found, return {{"nodes": [], "edges": []}}.
"""
        
        try:
            topo_response = await llm.ainvoke(
                [
                    SystemMessage(content="You are a topology analysis specialist. Extract entity relationships from technical evidence. Output only valid JSON."),
                    HumanMessage(content=topo_prompt)
                ],
                response_format={"type": "json_object"},
            )
            topo_json = json.loads(topo_response.content.strip().replace("```json", "").replace("```", ""))
            
            # Parse nodes
            for n in topo_json.get("nodes", []):
                new_nodes.append(TopologyNode(
                    id=n.get("id", ""),
                    node_type=n.get("node_type", "unknown"),
                    label=n.get("label", ""),
                    metadata=n.get("metadata", {}),
                    evidence_ref=ref.id,
                ))
            
            # Parse edges
            for e in topo_json.get("edges", []):
                new_edges.append(TopologyEdge(
                    source_id=e.get("source_id", ""),
                    target_id=e.get("target_id", ""),
                    relation=e.get("relation", "connects_to"),
                    direction=e.get("direction", "uni"),
                    metadata=e.get("metadata", {}),
                    confidence=float(e.get("confidence", 0.5)),
                    evidence_ref=ref.id,
                ))
            
            logger.info(f"Enricher: Extracted {len(topo_json.get('nodes', []))} nodes, {len(topo_json.get('edges', []))} edges from {ref.id[:8]}")
            
        except Exception as e:
            logger.warning(f"Enricher: Topology extraction failed for {ref.id[:8]}: {e}")
        
        processed_evidence_ids.append(ref.id)
              
    enriched_facts["_processed_evidence_ids"] = processed_evidence_ids
    
    # ─── Merge Topology (deduplicate) ────────────────────────────
    merged_nodes = _merge_nodes(existing_nodes, new_nodes)
    merged_edges = _merge_edges(existing_edges, new_edges)
    
    logger.info(f"Enricher: Topology graph now has {len(merged_nodes)} nodes, {len(merged_edges)} edges")
    
    return {
        "facts": enriched_facts,
        "structured_facts": structured_facts,
        "topology_nodes": merged_nodes,
        "topology_edges": merged_edges,
        "case_status": "synthesizing",
    }


def _merge_nodes(existing: List, new: List[TopologyNode]) -> List[TopologyNode]:
    """Deduplicate nodes by ID, keeping the latest version."""
    seen = {}
    for n in existing:
        node = n if isinstance(n, TopologyNode) else TopologyNode(**n)
        seen[node.id] = node
    for n in new:
        if n.id and n.id not in seen:
            seen[n.id] = n
    return list(seen.values())


def _merge_edges(existing: List, new: List[TopologyEdge]) -> List[TopologyEdge]:
    """Deduplicate edges by (source_id, target_id, relation). Higher confidence wins."""
    seen = {}
    for e in existing:
        edge = e if isinstance(e, TopologyEdge) else TopologyEdge(**e)
        key = (edge.source_id, edge.target_id, edge.relation)
        seen[key] = edge
    for e in new:
        key = (e.source_id, e.target_id, e.relation)
        if key not in seen or e.confidence > seen[key].confidence:
            seen[key] = e
    return list(seen.values())
