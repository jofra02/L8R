from typing import Any, Dict, List
from langchain_core.messages import SystemMessage, HumanMessage
import json
import asyncio

from src.core.models import GlobalState, EvidenceSnapshot, Component, PendingRequirement
from src.core.registry import CapabilityRegistry
from src.core.evidence_store import EvidenceStore
from src.core.llm import LLMFactory
from src.config import settings
from src.core.adaptive_executor import AdaptiveExecutor, MissingDependencyError
import logging

logger = logging.getLogger(__name__)

def _is_safe_tool(tool_name: str, tool_args: Dict[str, Any]) -> bool:
    """Checks if tool usage is safe against blocked keywords."""
    blocked = settings.SAFETY_BLOCKED_KEYWORDS
    
    # Check Name
    for kw in blocked:
        if kw in tool_name.lower():
            logger.warning(f"Safety Block: Tool '{tool_name}' blocked by keyword '{kw}'")
            return False
            
    # Check Args (e.g. "command": "execute ...")
    for key, val in tool_args.items():
        if isinstance(val, str):
            for kw in blocked:
                if kw in val.lower():
                    logger.warning(f"Safety Block: Tool '{tool_name}' arg '{key}'='{val}' blocked by keyword '{kw}'")
                    return False
    return True

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
    missing_info_list = []
    pending_requirements = []
    
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
                
                # SAFETY CHECK
                if not _is_safe_tool(tool_name, tool_args):
                     logger.warning(f"Skipping unsafe tool execution: {tool_name}")
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
                        # It is an executor. 
                        # Only overwrite if the LLM provided a placeholder or if it matches the ID
                        if tool_args["device"] in ["<device>", "DEVICE", ""] or tool_args["device"] == comp.id:
                             tool_args["device"] = comp.id
                    else:
                        pass

                # 2. Handle 'target'/'host'/'ip' arguments
                # These usually refer to the subject of the check
                for key in ["target", "host", "hostname", "ip", "address", "subnet", "destination"]:
                    if key in tool_args:
                         # Use component ID only if it's NOT an asset ID (heuristic) or if we don't have a better value
                         curr_val = tool_args[key]
                         if curr_val in ["<target>", "TARGET", ""] or curr_val == comp.id:
                             # Check if comp.id is an Asset ID (e.g. "asset:...") and tool needs IP?
                             # For now, we inject. The AdaptiveExecutor will catch mismatch.
                             tool_args[key] = comp.id

                logger.info(f"Evidence Collector: Executing {tool_name} with {tool_args}")
                try:
                    # ADAPTIVE EXECUTION
                    executor = AdaptiveExecutor()
                    # Context for diagnosis
                    facts_str = json.dumps(state.get("facts", {}), default=str)
                    context = f"Ticket: {ticket_text}\nComponent: {comp.id} ({comp.role})\nFacts: {facts_str}\nGoal: Collect evidence."
                    
                    output = await executor.execute(tool, tool_args, context)
                    
                    snapshot = await store.save_evidence(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        content=output
                    )
                    snapshot.tool_call_id = "auto"
                    new_evidence.append(snapshot)
                    logger.info(f"Collected evidence with {tool_name}")
                    
                except MissingDependencyError as missing_e:
                    logger.warning(f"AdaptiveExec Signal: Missing Info for {tool_name} -> {missing_e.description}")
                    
                    # --- INTERNAL RECOVERY LOOP ---
                    # The user wants the agent to "think" and "fix" immediately.
                    # We can try to finding a RESOLUTION tool.
                    logger.info(f"Attempting in-flight resolution for {missing_e.description}")
                    
                    resolution_context = f"""
                    Problem: Tool '{tool_name}' failed on component '{comp.id}'.
                    Missing: {missing_e.description}
                    Source Hint: {missing_e.suggested_source}
                    
                    Task: Select a DIFFERENT tool to FETCH this missing information from the component itself (or inventory).
                    Ex: If IP is missing, run 'get_system_interface' or similar.
                    """
                    
                    try:
                        # Re-use the selection logic but focused on resolution
                        # We do a quick search for "get" or "show" tools
                        resolution_tools = await _select_resolution_tool(llm, comp, resolution_context)
                        
                        if resolution_tools:
                            res_tool_def = resolution_tools[0] # Pick top 1
                            res_tool_name = res_tool_def["name"]
                            res_tool_args = res_tool_def["args"]
                            
                            # Inject device ID if needed (Resolution usually runs ON the device)
                            if "device" in res_tool_args and is_executor:
                                res_tool_args["device"] = comp.id
                                
                            logger.info(f"Recovery: Executing resolution tool {res_tool_name}")
                            
                            # Execute Resolution Tool
                            res_tool = CapabilityRegistry.get_tool(res_tool_name)
                            if res_tool:
                                res_output = await executor.execute(res_tool, res_tool_args, context)
                                
                                # Save the resolution output as evidence (it likely contains the IP!)
                                res_snapshot = await store.save_evidence(
                                    tool_name=res_tool_name,
                                    tool_args=res_tool_args,
                                    content=res_output,
                                    summary=f"Resolution for {missing_e.description}"
                                )
                                new_evidence.append(res_snapshot)
                                
                                # Note: We don't automatically retry the ORIGINAL tool here because parsing the IP 
                                # from the text output is complex without another LLM call.
                                # But getting the evidence IS the success. The next iteration/agent will see the IP in evidence.
                                logger.info(f"Recovery successful: Collected info via {res_tool_name}")
                                continue # Move to next tool, satisfied.
                                
                    except Exception as res_e:
                        logger.error(f"Recovery failed: {res_e}")

                    # If recovery didn't work or we just saved evidence, add to missing list as backup
                    req = PendingRequirement(
                        key=f"missing_{tool_name}_{comp.id}",
                        description=missing_e.description,
                        source_hint=missing_e.suggested_source,
                        tool_name=tool_name,
                        component_id=comp.id
                    )
                    pending_requirements.append(req)
                    
                    # Also keep legacy simple string list for now
                    missing_info_list.append(f"{missing_e.description} ({comp.id})")
                    
                    continue 

                except Exception as e:
                    logger.error(f"Tool execution failed {tool_name}: {e}")
                    # Capture failure as evidence so it appears in the report
                    fail_snapshot = await store.save_evidence(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        content=f"EXECUTION FAILED: {str(e)}",
                        summary=f"Failed to run {tool_name}: {str(e)[:100]}"
                    )
                    new_evidence.append(fail_snapshot)
            
        except Exception as e:
            logger.error(f"Failed to collect evidence for {comp.id}: {e}")

    return {
        "evidence_refs": evidence_refs + new_evidence,
        "missing_info": missing_info_list,
        "pending_requirements": pending_requirements
    }

async def _select_resolution_tool(llm, component, context_str) -> List[Dict[str, Any]]:
    """Helper to select a tool to resolve missing info."""
    prompt = f"""
    Context: {context_str}
    
    Available Tools (Heuristic): We need 'get', 'show', 'status', 'list' tools for {component.vendor or 'generic'}.
    
    Task: Select ONE read-only tool to retrieve the missing information.
    Return JSON: [ {{ "name": "tool", "args": {{ ... }} }} ]
    """
    try:
         # We rely on the LLM's internal knowledge of tools or we could inject tool list
         # For speed, let's assume it knows standard tools or we use searching
         # Better: Search specifically for "info" or "status"
         found = CapabilityRegistry.search_tools("status info get", limit=10)
         tools_json = json.dumps([{'name': t.name, 'description': t.description} for t in found])
         
         full_prompt = prompt + f"\nChoose from:\n{tools_json}"
         
         response = await llm.ainvoke([SystemMessage(content="You are a Recovery Specialist."), HumanMessage(content=full_prompt)])
         return json.loads(response.content.strip().replace("```json", "").replace("```", ""))
    except:
         return []

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
    Focus on the vendor/technology and the action.
    
    CRITICAL GUIDELINES:
    1. INCLUDE terms related to 'observability', 'status', 'health', 'checking', or 'retrieving' configuration.
    2. EXCLUDE/BAN terms that imply high-load debugging or modification:
       - NO "debug flow", "sniffer", "packet capture", "pcap"
       - NO "execute", "set", "configure", "edit"
       
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

    # Fetch insights for these tools to proactively avoid errors
    from src.core.qdrant import vector_store
    insights_text = ""
    try:
        combined_insights = []
        for t_name in unique_tools.keys():
            insights = await vector_store.get_tool_insights(t_name, limit=1)
            for ins in insights:
                combined_insights.append(f"For {t.name}: {ins.get('insight')}")
        
        if combined_insights:
            insights_text = "LEARNED BEST PRACTICES:\n" + "\n".join(combined_insights)
    except Exception as e:
        logger.warning(f"Failed to fetch insights: {e}")

    # Step C: Select Multiple Tools
    select_prompt = f"""
    Context:
    Ticket: "{ticket_text}"
    Component: {component.id} (Role: {component.role}, {vendor_context})
    
    Available Tools:
    {tool_descriptions}
    
    {insights_text}

    Task: Select ALL valuable tools to diagnose the issue. 
    Don't limit yourself to one. If multiple tools provide different angles (e.g. one checks health, one checks logs), select them all.
    Construct the arguments for each tool.
    
    GUIDELINES:
    1. CRITICAL: For tools requiring a 'device', 'target', 'host', or 'ip' argument, YOU MUST DECIDE the correct value.
       - If {component.id} is a valid hostname/IP, use it.
       - If {component.id} is an Inventory/Asset ID and the tool requires an IP/Address, DO NOT USE THE ID. 
         Instead, select a 'Discovery Tool' (get_system, get_status, show_interface) to find the address first.
    2. Analyze the Schema: Distinguish between Mandatory and Optional arguments.
    3. ANTI-HALLUCINATION: Do NOT invent parameters. If an optional parameter is unknown, OMIT IT. If a mandatory parameter is missing, skip the tool.
    4. SAFETY: Do NOT select tools that modify configuration (set, edit, delete) or perform intrusive debugging. READ-ONLY only.
    
    SPECIAL RULE FOR TARGETS:
    If this component ({component.id}) is a Network/Subnet/IP (not a firewall/server), DO NOT use it as the 'device' argument. 
    Use it as 'target', 'subnet', or 'address' as appropriate.
    
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
