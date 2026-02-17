from typing import Any, Dict, List
from langchain_core.messages import SystemMessage, HumanMessage
import json
import asyncio

from src.core.models import GlobalState, EvidenceSnapshot, Component
from src.core.registry import CapabilityRegistry
from src.core.evidence_store import EvidenceStore
from src.core.llm import LLMFactory
import logging

logger = logging.getLogger(__name__)

async def evidence_collector_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Collects evidence using Vendor-Agnostic Smart Selection & Brute Force Fallback.
    """
    ticket_text = state["ticket"].text
    components = state.get("components", [])
    evidence_refs: List[EvidenceSnapshot] = state.get("evidence_refs", [])
    
    logger.info(f"Evidence Collector: Processing {len(components)} components.")
    
    store = EvidenceStore()
    llm = LLMFactory.get_fast_llm()
    
    new_evidence = []
    
    for comp in components:
        try:
            # 1. Select Tools via LLM (Multi-Select)
            selected_tools = await _select_tools_for_component(llm, comp, ticket_text)
            
            # 2. Brute Force Fallback if no tools selected
            if not selected_tools:
                logger.warning(f"No suitable tool found for {comp.id} via Smart Selection. Triggering Brute Force Fallback.")
                selected_tools = _get_brute_force_tools(comp)
            
            if not selected_tools:
                logger.error(f"Fallback failed. No tools to run for {comp.id}")
                continue

            # 3. Execute All Selected Tools
            for tool_def in selected_tools:
                tool_name = tool_def["name"]
                tool_args = tool_def["args"]
                
                tool = CapabilityRegistry.get_tool(tool_name)
                if not tool:
                    logger.warning(f"Tool {tool_name} not found in registry.")
                    continue
                
                # Smart Argument Injection based on Component Role
                # We distinguish between EXECUTORS (Devices) and TARGETS (Subnets, IPs, etc.)
                
                # Roles that can act as a 'device' executor
                EXECUTOR_ROLES = ["firewall", "router", "switch", "server", "host", "loadbalancer"]
                
                # Roles that are usually targets
                TARGET_ROLES = ["subnet", "network", "ip", "address", "url", "service", "process"]
                
                comp_role_norm = comp.role.lower()
                is_executor = any(r in comp_role_norm for r in EXECUTOR_ROLES)
                
                # 1. Handle 'device' argument
                if "device" in tool_args:
                    if is_executor:
                        # It is an executor, so IT is the device
                        tool_args["device"] = comp.id
                    else:
                        # It is NOT an executor (e.g. it's a subnet). 
                        # DO NOT overwrite 'device' with this component ID.
                        # Leave it to the LLM's selection or default.
                        pass

                # 2. Handle 'target'/'host'/'ip' arguments
                # These usually refer to the subject of the check
                for key in ["target", "host", "hostname", "ip", "address", "subnet", "destination"]:
                    if key in tool_args:
                         # For targets, we almost always want to swap in the ID
                         tool_args[key] = comp.id
                    
                logger.info(f"Evidence Collector: Executing {tool_name} with {tool_args}")
                try:
                    output = await tool.run(**tool_args)
                    
                    snapshot = await store.save_evidence(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        content=output
                    )
                    snapshot.tool_call_id = "auto"
                    new_evidence.append(snapshot)
                    logger.info(f"Collected evidence with {tool_name}")
                except Exception as e:
                    logger.error(f"Tool execution failed {tool_name}: {e}")
            
        except Exception as e:
            logger.error(f"Failed to collect evidence for {comp.id}: {e}")

    return {
        "evidence_refs": evidence_refs + new_evidence,
        "missing_info": [] 
    }

async def _select_tools_for_component(llm, component: Component, ticket_text: str) -> List[Dict[str, Any]]:
    """
    Uses LLM to find and select MULTIPLE tools.
    Returns List[{"name": str, "args": dict}].
    """
    vendor_context = f"Vendor: {component.vendor}" if component.vendor else "Vendor: Unknown (Infer from tool availability)"
    
    # Step A: Keyword Search
    search_prompt = f"""
    Context:
    Ticket: "{ticket_text}"
    Component: {component.id} (Role: {component.role}). {vendor_context}
    
    Task: Identify 3-5 specific keywords to search for diagnostic tools. 
    Focus on the vendor/technology (e.g. 'fortigate', 'cisco', 'linux') and the action.
    CRITICAL: Include terms like 'monitor', 'status', 'health', 'check', 'get' to prioritize observability.
    
    Return ONLY a JSON list of strings.
    """
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content="You are an expert Network Engineer."),
            HumanMessage(content=search_prompt)
        ])
        keywords = json.loads(response.content.strip().replace("```json", "").replace("```", ""))
    except Exception as e:
        logger.warning(f"LLM Keyword generation failed: {e}")
        keywords = [component.role, "status"]
        if component.vendor:
            keywords.insert(0, component.vendor)
            
    logger.info(f"Generated keywords for {component.id}: {keywords}")
        
    # Step B: Perform Search & Deduplicate
    candidate_tools = []
    for kw in keywords:
        found = CapabilityRegistry.search_tools(kw, limit=5)
        candidate_tools.extend(found)
        
    unique_tools = {t.name: t for t in candidate_tools}
    logger.info(f"Found {len(unique_tools)} unique tools for {component.id}")
    
    # Always ensure basic ping is available as an option
    if "ping" in CapabilityRegistry._tools:
        unique_tools["ping"] = CapabilityRegistry._tools["ping"]

    if not unique_tools:
        return []

    tool_descriptions = "\n".join([
        f"- {t.name}: {t.description}\n  Args: {json.dumps(t.args_schema.model_json_schema()) if t.args_schema else 'None'}"
        for t in unique_tools.values()
    ])

    # Step C: Select Multiple Tools
    select_prompt = f"""
    Context:
    Ticket: "{ticket_text}"
    Component: {component.id} (Role: {component.role}, {vendor_context})
    
    Available Tools:
    {tool_descriptions}
    
    Task: Select ALL valuable tools to diagnose the issue. 
    Don't limit yourself to one. If multiple tools provide different angles (e.g. one checks health, one checks logs), select them all.
    Construct the arguments for each tool.
    
    GUIDELINES:
    1. CRITICAL: For tools requiring a 'device', 'target', 'host', or 'ip' argument, USE "{component.id}" as the value.
    2. Analyze the Schema: Distinguish between Mandatory and Optional arguments.
    3. ANTI-HALLUCINATION: Do NOT invent parameters. If an optional parameter is unknown (e.g. 'srcintf'), OMIT IT. If a mandatory parameter is missing, skip the tool.
    
    SPECIAL RULE FOR TARGETS:
    If this component ({component.id}) is a Network/Subnet/IP (not a firewall/server), DO NOT use it as the 'device' argument. 
    Use it as 'target', 'subnet', or 'address'. The 'device' argument should refer to the gateway or firewall managing it (if known), or be omitted.
    
    Return ONLY a JSON LIST of objects:
    [
        {{ "name": "tool_name_1", "args": {{ ... }} }},
        {{ "name": "tool_name_2", "args": {{ ... }} }}
    ]
    """
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content="You are an expert Network Engineer. Select comprehensive diagnostic tools."),
            HumanMessage(content=select_prompt)
        ])
        selection = json.loads(response.content.strip().replace("```json", "").replace("```", ""))
        if isinstance(selection, dict): # Handle case where LLM returns single object instead of list
            selection = [selection]
        return selection
    except Exception as e:
        logger.error(f"LLM Tool Selection failed: {e}")
        return []

def _get_brute_force_tools(component: Component) -> List[Dict[str, Any]]:
    """
    Fallback: Returns a list of all SAFE 'get'/'check' tools matching the component's vendor/role.
    """
    all_tools = CapabilityRegistry.list_tools()
    candidates = []
    
    # Simple heuristic filters
    role_kw = component.role.lower()
    vendor_kw = component.vendor.lower() if component.vendor else ""
    
    for t in all_tools:
        name = t.name.lower()
        if "delete" in name or "remove" in name or "shutdown" in name or "reboot" in name:
             continue # Unsafe
        
        # Must start with 'get', 'check', 'monitor', 'list', 'show'
        if not any(name.startswith(p) for p in ["get", "check", "monitor", "list", "show", "fgt_monitor", "fgt_get"]):
             continue
             
        # Match vendor if known
        if vendor_kw and vendor_kw not in name:
             continue
             
        # Match role/context if possible (loose match)
        # For FortiGate tools (fgt_), we assume they match if vendor is Fortinet
        if vendor_kw == "fortinet" and "fgt_" in name:
             # Heuristic: Pick a small subset of general health tools to avoid running 2000 commands
             if any(k in name for k in ["health", "status", "info", "system"]):
                 candidates.append({"name": t.name, "args": {"device": component.id}}) # Assume 'device' arg for fgt
        
        elif "ping" in name:
             candidates.append({"name": t.name, "args": {"target": component.id}})

    # Limit brute force to top 5 to prevent overload
    return candidates[:5]
