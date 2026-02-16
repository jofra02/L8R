from typing import Any, Dict, List
from src.core.models import GlobalState, EvidenceSnapshot
from src.core.registry import CapabilityRegistry
from src.core.evidence_store import EvidenceStore
from src.mcp.client import MCPClient
import logging

logger = logging.getLogger(__name__)

async def evidence_collector_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Collects evidence for components.
    """
    components = state.get("components", [])
    evidence_refs: List[EvidenceSnapshot] = state.get("evidence_refs", [])
    
    logger.info(f"Evidence Collector: Processing {len(components)} components.")
    
    store = EvidenceStore()
    client = MCPClient() # In real app, we might inject connection details
    
    new_evidence = []
    
    # Simple strategy for MVP: Trigger 'status' tool for each component if available
    for comp in components:
        tool_name = "generic_status" # Placeholder
        
        # Check if tool exists
        # tool = CapabilityRegistry.get_tool(tool_name)
        # if not tool: continue
        
        try:
            # Execute
            output = await client.execute_tool(tool_name, {"target": comp.id})
            
            # Persist
            snapshot = await store.save_evidence(
                tool_name=tool_name,
                tool_args={"target": comp.id},
                content=output
            )
            snapshot.tool_call_id = "auto" # Replace with real ID
            
            new_evidence.append(snapshot)
            logger.info(f"Collected evidence for {comp.id}")
            
        except Exception as e:
            logger.error(f"Failed to collect evidence for {comp.id}: {e}")

    return {
        "evidence_refs": evidence_refs + new_evidence,
        "missing_info": [] # Clear missing info if we collected something?
    }
