from typing import Any, Dict, List
from langchain_core.messages import SystemMessage, HumanMessage
import json
import asyncio

from src.core.models import GlobalState, EvidenceSnapshot, Component, PendingRequirement
from src.core.registry import CapabilityRegistry
from src.core.evidence_store import EvidenceStore
from src.core.llm import LLMFactory
from src.core.safety import is_safe_tool, is_tool_allowed_for_tenant
from src.config import settings
from src.core.adaptive_executor import AdaptiveExecutor, MissingDependencyError
import logging

logger = logging.getLogger(__name__)

# Module-level tenant context for _select_tools_for_component
_current_customer_id: str = "unknown"


async def evidence_collector_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Collects evidence using Vendor-Agnostic Smart Selection & Brute Force Fallback.
    """
    ticket_text = state["ticket"].text
    components = state.get("components", [])
    evidence_refs: List[EvidenceSnapshot] = state.get("evidence_refs", [])
    
    logger.info(f"Evidence Collector: Processing {len(components)} components.")
    
    store = EvidenceStore(
        customer_id=state.get("customer_id", "unknown"),
        run_id=state.get("meta", {}).get("run_id")
    )
    llm = LLMFactory.get_model_for_agent("evidence_collector")
    
    new_evidence = []
    missing_info_list = []
    pending_requirements = []
    
    # Set module-level tenant context for semantic search
    global _current_customer_id
    _current_customer_id = state.get("customer_id", "unknown")
    
    # Build path analysis context for topology-aware intents
    path_analysis = state.get("path_analysis")
    path_context = ""
    if path_analysis:
        pa = path_analysis if hasattr(path_analysis, 'suggested_probes') else type('PA', (), path_analysis)()
        probes = pa.suggested_probes if hasattr(pa, 'suggested_probes') else path_analysis.get('suggested_probes', [])
        missing = pa.missing_evidence if hasattr(pa, 'missing_evidence') else path_analysis.get('missing_evidence', [])
        if probes or missing:
            parts = []
            if missing:
                parts.append("Missing evidence: " + "; ".join(missing[:5]))
            if probes:
                parts.append("Suggested probes: " + "; ".join(probes[:5]))
            path_context = "\n".join(parts)
    
    for comp in components:
        try:
            # 1. Select Tools via LLM (Multi-Select)
            selected_tools = await _select_tools_for_component(llm, comp, ticket_text, path_context)
            
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
                if not is_safe_tool(tool_name, tool_args):
                     logger.warning(f"Skipping unsafe tool execution: {tool_name}")
                     continue
                
                # GOVERNANCE CHECK (CapabilityScope)
                customer_id = state.get("customer_id", "unknown")
                if not await is_tool_allowed_for_tenant(tool_name, customer_id):
                     logger.warning(f"Skipping tool {tool_name}: not allowed for tenant {customer_id}")
                     continue
                
                # Smart Argument Injection based on Component Role
                # We distinguish between EXECUTORS (Devices) and TARGETS (Subnets, IPs, etc.)
                
                # Roles that can act as a 'device' executor
                EXECUTOR_ROLES = ["firewall", "router", "switch", "server", "host", "loadbalancer",
                                  "appliance", "controller", "gateway", "hypervisor", "node", "cluster",
                                  "database", "storage", "nas", "san"]
                
                # Roles that are usually targets
                TARGET_ROLES = ["subnet", "network", "ip", "address", "url", "service", "process",
                                "endpoint", "user", "application", "container", "pod", "vm", "instance"]
                
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
                    deps_str = "; ".join(missing_e.dependencies)
                    logger.warning(f"AdaptiveExec Signal: Missing Info for {tool_name} -> {deps_str}")
                    
                    # --- INTERNAL RECOVERY LOOP ---
                    # The user wants the agent to "think" and "fix" immediately.
                    # We can try to finding a RESOLUTION tool.
                    logger.info(f"Attempting in-flight resolution for {deps_str}")
                    
                    resolution_context = f"""
                    Problem: Tool '{tool_name}' failed on component '{comp.id}'.
                    Missing: {deps_str}
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
                                    summary=f"Resolution for {deps_str}"
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
                        description=deps_str,
                        source_hint=missing_e.suggested_source,
                        tool_name=tool_name,
                        component_id=comp.id
                    )
                    pending_requirements.append(req)
                    
                    # Also keep legacy simple string list for now
                    missing_info_list.append(f"{deps_str} ({comp.id})")
                    
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

async def _select_tools_for_component(llm, component: Component, ticket_text: str, path_context: str = "") -> List[Dict[str, Any]]:
    """
    Uses LLM to describe MULTIPLE specific diagnostic intents, 
    then semantic vector search for each to find comprehensive tools.
    Returns List[{"name": str, "args": dict}].
    """
    vendor_context = f"Vendor: {component.vendor}" if component.vendor else "Vendor: Unknown"
    
    # Step A: LLM generates MULTIPLE specific diagnostic intents
    intent_prompt = f"""
Context:
Ticket: "{ticket_text}"
Component: {component.id} (Role: {component.role}). {vendor_context}

Task: You are preparing a comprehensive diagnostic data collection plan.
Generate 3-5 SPECIFIC diagnostic queries that describe what data you need to collect.

Each query should target a DIFFERENT diagnostic angle, for example:
- Status/Health: "retrieve current operational status and health indicators"
- Configuration: "get the active configuration relevant to the reported issue"  
- Logs/Events: "list recent logs or events related to the affected component"
- Connectivity: "check connectivity and reachability of the affected path"
- Resources: "retrieve resource utilization metrics such as CPU, memory, and uptime"

RULES:
1. Be SPECIFIC — mention the exact data type you need (status table, log entries, active config, etc.)
2. DO NOT mention tool names — describe the DATA you want
3. Each query should be 1 sentence, focused on ONE diagnostic area
4. Cover the diagnostic areas most relevant to the ticket issue
5. Tailor your queries to the component's role and the reported problem
{f"""
6. PRIORITY — The following evidence gaps have been identified by path analysis. Generate intents that specifically address these:
{path_context}
""" if path_context else ""}
Return ONLY a JSON object:
{{"intents": ["query 1", "query 2", "query 3"]}}
"""
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content="You are an expert IT Systems Engineer performing systematic diagnostics."),
            HumanMessage(content=intent_prompt)
        ])
        parsed = json.loads(response.content.strip().replace("```json", "").replace("```", ""))
        intents = parsed.get("intents", [f"{component.role} status and health check"])
        if isinstance(intents, str):
            intents = [intents]
    except Exception as e:
        logger.warning(f"LLM intent generation failed: {e}")
        intents = [
            f"{component.role} status health diagnostics",
            f"{component.role} configuration and operational state",
            f"{component.role} recent logs and events",
        ]
    
    logger.info(f"Diagnostic intents for {component.id}: {intents}")
    
    # Step B: Semantic vector search for EACH intent, merge + deduplicate
    from src.core.qdrant import vector_store
    
    candidate_tools = {}
    
    for intent in intents:
        try:
            tool_payloads = await vector_store.search_tool_catalog(
                intent=intent,
                customer_id=_current_customer_id,
                limit=5,  # Top 5 per intent
            )
            
            for payload in tool_payloads:
                t_name = payload.get("tool_name")
                if t_name and t_name not in candidate_tools:
                    tool = CapabilityRegistry.get_tool(t_name)
                    if tool:
                        candidate_tools[t_name] = tool
        except Exception as e:
            logger.warning(f"Semantic search failed for intent '{intent[:50]}': {e}")
    
    logger.info(f"Semantic search found {len(candidate_tools)} unique tools for {component.id}")
    
    # Fallback to keyword search if semantic returned nothing
    if not candidate_tools:
        for kw in [component.role, component.vendor or "status", "health"]:
            for t in CapabilityRegistry.search_tools(kw, limit=5):
                candidate_tools[t.name] = t
    
    if not candidate_tools:
        return []

    tool_descriptions = "\n".join([
        f"- {t.name}: {t.description}\n  Args: {json.dumps(t.args_schema.model_json_schema()) if t.args_schema else 'None'}"
        for t in candidate_tools.values()
    ])

    # Fetch insights for these tools
    insights_text = ""
    try:
        combined_insights = []
        for t_name in candidate_tools.keys():
            insights = await vector_store.get_tool_insights(t_name, limit=1)
            for ins in insights:
                combined_insights.append(f"For {t_name}: {ins.get('insight')}")
        
        if combined_insights:
            insights_text = "LEARNED BEST PRACTICES:\n" + "\n".join(combined_insights)
    except Exception as e:
        logger.warning(f"Failed to fetch insights: {e}")

    # Step C: LLM selects tools + configures args
    select_prompt = f"""
Context:
Ticket: "{ticket_text}"
Component: {component.id} (Role: {component.role}, {vendor_context})

Available Tools:
{tool_descriptions}

{insights_text}

Task: Select ALL valuable tools to diagnose the issue. 
Don't limit yourself to one. If multiple tools provide different angles, select them all.
Construct the arguments for each tool.

GUIDELINES:
1. CRITICAL: For tools requiring 'device', 'target', 'host', or 'ip': 
   - If {component.id} is a valid hostname/IP, use it.
   - If it's an Asset ID, select a Discovery Tool first to find the address.
2. Analyze the Schema: Distinguish between Mandatory and Optional arguments.
3. ANTI-HALLUCINATION: Do NOT invent parameters. If mandatory param is missing, skip that tool.
4. SAFETY: READ-ONLY tools only. No modify/delete/configure.

Return ONLY a JSON LIST:
[
    {{ "name": "tool_name_1", "args": {{ ... }} }},
    {{ "name": "tool_name_2", "args": {{ ... }} }}
]
"""
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content="You are an expert IT Systems Engineer. Select comprehensive diagnostic tools."),
            HumanMessage(content=select_prompt)
        ])
        selection = json.loads(response.content.strip().replace("```json", "").replace("```", ""))
        if isinstance(selection, dict):
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
        
        # Must be a read-only operation prefix
        if not any(name.startswith(p) for p in ["get", "check", "monitor", "list", "show", "describe", "fetch"]):
             continue
             
        # Match vendor if known
        if vendor_kw and vendor_kw not in name:
             continue
             
        # Match general health/status tools for the matched vendor
        if any(k in name for k in ["health", "status", "info", "system", "summary", "overview"]):
            candidates.append({"name": t.name, "args": {"device": component.id}})
        
        # External tools only handled natively

    # Limit brute force to top 5 to prevent overload
    return candidates[:5]
