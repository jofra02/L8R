from typing import Any, Dict, List
from src.core.models import GlobalState, Hypothesis, PendingRequirement
from src.core.llm import LLMFactory
from src.core.registry import CapabilityRegistry
from src.core.evidence_store import EvidenceStore
from src.config import settings
from src.core.adaptive_executor import AdaptiveExecutor, MissingDependencyError
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
import logging
import json

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

async def investigator_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Selects top hypothesis and executes specific verification tools.
    """
    hypotheses = state.get("hypotheses", [])
    
    # 1. Select Target Hypothesis
    # We want to finish 'verifying' ones (unblock them) or start 'proposed' ones.
    candidates = [h for h in hypotheses if h.status in ["proposed", "verifying"]]
    
    # Sort: 
    # 1. 'verifying' first (Stick to the active thread)
    # 2. Then by Rank
    candidates.sort(key=lambda x: (0 if x.status == "verifying" else 1, x.rank))
    
    if not candidates:
        logger.info("Investigator: No proposed hypotheses to verify.")
        return {}
        
    target_hypothesis = candidates[0]
    logger.info(f"Investigator: Verifying Hypothesis (Rank {target_hypothesis.rank}): {target_hypothesis.summary}")
    
    llm = LLMFactory.get_model_for_agent("investigator")
    store = EvidenceStore()
    
    # 2. Formulate Verification Plan
    # Ask LLM what to do to verify this SPECIFIC hypothesis
    plan_prompt = f"""
    Context:
    Ticket: {state['ticket'].text}
    Hypothesis: {target_hypothesis.summary}
    Components: {[c.id for c in state.get('components', [])]}
    
    Task: Identify the SINGLE most effective diagnostic tool execution to verify or disprove this hypothesis.
    Focus on "proving" the hypothesis.
    
    Return a JSON object with:
    - "search_query": Space-separated keywords to find tools (e.g. "firewall policy lookup", "interface status", NOT a full sentence).
    - "reasoning": Why this tool?
    """
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content="You are an expert IT Troubleshooter."),
            HumanMessage(content=plan_prompt)
        ])
        plan = json.loads(response.content.strip().replace("```json", "").replace("```", ""))
        search_query = plan.get("search_query", "ping")
        logger.info(f"Investigator: Search Query: {search_query}")
        
    except Exception as e:
        logger.error(f"Investigator: Plan generation failed: {e}")
        return {}
        
    # 3. Find Tools
    tools = CapabilityRegistry.search_tools(search_query, limit=5)
    if not tools:
        logger.warning(f"Investigator: No tools found for query '{search_query}'. Fallback to ping.")
        tools = CapabilityRegistry.search_tools("ping", limit=1)
        
    # 4. Select & Configure Tool
    # Ask LLM to pick the best tool and define args (linking to components)
    
    # Context Injection
    facts = state.get("facts", {})
    evidence_list = state.get("evidence_refs", [])
    evidence_context = "\n".join([f"- {e.tool_name}: {e.summary}" for e in evidence_list[-5:]]) # Last 5 items

    # Fetch insights
    from src.core.qdrant import vector_store
    insights_text = ""
    try:
        combined_insights = []
        for t in tools:
            insights = await vector_store.get_tool_insights(t.name, limit=1)
            for ins in insights:
                combined_insights.append(f"For {t.name}: {ins.get('insight')}")
        if combined_insights:
            insights_text = "LEARNED BEST PRACTICES:\n" + "\n".join(combined_insights)
    except Exception as e:
        logger.warning(f"Investigator failed to fetch insights: {e}")
    
    tool_select_prompt = f"""
    Applicable Tools:
    {json.dumps([{'name': t.name, 'description': t.description, 'args': t.args_schema.model_json_schema()} for t in tools], indent=2)}
    
    {insights_text}

    Hypothesis: {target_hypothesis.summary}
    Components: {json.dumps([c.model_dump() for c in state.get('components', [])], default=str)}
    Facts: {json.dumps(facts, default=str)}
    Previous Evidence:
    {evidence_context}
    
    Task: Select the best tool and configure arguments.
    
    GUIDELINES:
    1. Analyze the Schema: Distinguish between Mandatory (Required) and Optional arguments. 
    2. Context Check: Look for parameter values (like 'interface_name', 'policy_id', 'protocol') in the provided 'Facts', 'Components', and 'Evidence'.
    3. CRITICAL: Use Component IDs for 'device', 'target', 'host' arguments.
    4. ANTI-HALLUCINATION: If a MANDATORY parameter is missing from the context, DO NOT INVENT IT. 
       - If you cannot fill a mandatory param, do NOT select that tool. Choose a simpler tool (like `get_status` or `ping`) that requires fewer args.
    5. BLOCKED TOOLS: Check 'Previous Evidence' for "BLOCKED" or "Missing Info" regarding specific tools.
       - If a tool was recently BLOCKED due to missing info, DO NOT retry it unless you see the missing info in 'Facts' or 'Evidence'.
       - Instead, select a **Discovery Tool** (e.g., `get_interfaces`, `show_system`, `get_routes`) to FIND that missing information.
    6. SAFETY: Do NOT select tools that modify configuration (set, edit, delete) or perform intrusive debugging. READ-ONLY only.
    
    Return JSON:
    {{
        "tool_name": "name",
        "arguments": {{ "arg": "value" }}
    }}
    """
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content="You are an expert Automation Engineer."),
            HumanMessage(content=tool_select_prompt)
        ])
        selection = json.loads(response.content.strip().replace("```json", "").replace("```", ""))
        tool_name = selection["tool_name"]
        tool_args = selection["arguments"]
        
    except Exception as e:
        logger.error(f"Investigator: Tool selection failed: {e}")
        return {}
        
    # 5. Execute
    tool = CapabilityRegistry.get_tool(tool_name)
    if tool:
        # Sanitize arguments: Ensure 'device'/'target' maps to a real Component ID
        components = state.get("components", [])
        
        # Roles that can be actual devices
        EXECUTOR_ROLES = ["firewall", "router", "switch", "server", "host"]
        
        for key in ["device", "target", "host", "hostname", "ip"]:
            if key in tool_args:
                val = tool_args[key]
                
                # Try to find a matching component
                # 1. Exact ID Match
                match = next((c for c in components if c.id == val), None)
                
                # 2. Ref/Role Match (Auto-correct)
                if not match:
                     match = next((c for c in components if c.ref.lower() == str(val).lower() or c.role.lower() == str(val).lower()), None)
                     
                if match:
                    # SMART CHECK: Only use this component as 'device' if it is an EXECUTOR
                    if key == "device":
                        is_executor = any(r in match.role.lower() for r in EXECUTOR_ROLES)
                        if is_executor:
                             logger.info(f"Investigator: Auto-correcting argument {key}='{val}' -> '{match.id}'")
                             tool_args[key] = match.id
                        else:
                             logger.warning(f"Investigator: Prevented using non-executor '{match.id}' ({match.role}) as 'device'.")
                    else:
                        # For target/host/ip, it's safe to use any component
                        logger.info(f"Investigator: Auto-correcting argument {key}='{val}' -> '{match.id}'")
                        tool_args[key] = match.id
        
        # SAFETY CHECK
        if not _is_safe_tool(tool_name, tool_args):
             logger.warning(f"Investigator: Skipping unsafe tool execution: {tool_name}")
             return {}

        try:
            logger.info(f"Investigator: Executing {tool_name} with {tool_args}")
            
            # ADAPTIVE EXECUTION
            executor = AdaptiveExecutor()
            facts_str = json.dumps(state.get("facts", {}), default=str)
            context = f"Ticket: {state['ticket'].text}\nFacts: {facts_str}\nHypothesis: {target_hypothesis.summary}\nGoal: Verify hypothesis."
            
            output = await executor.execute(tool, tool_args, context)
            
            # Save Evidence
            snapshot = await store.save_evidence(
                tool_name=tool_name,
                tool_args=tool_args,
                content=output,
                summary=f"Verification for hypothesis: {target_hypothesis.summary}"
            )
            
            # Mark Hypothesis as 'verifying' (The Hypothesis Agent will re-evaluate and mark verified/rejected)
            # We return the updated list in state to modify status immediately
            target_hypothesis.status = "verifying"
            
            # Append new evidence to state
            current_evidence = state.get("evidence_refs", [])
            updated_evidence = current_evidence + [snapshot]
            
            return {
                "hypotheses": hypotheses,
                "evidence_refs": updated_evidence
            } # Update state
            
        except MissingDependencyError as e:
            deps_str = "\n- ".join(e.dependencies)
            logger.warning(f"Investigator: Blocked by Missing Dependencies:\n- {deps_str}")
            
            # 1. SAVE THE FAILURE EVIDENCE FIRST
            # So the report shows "Tool X Failed"
            fail_snapshot = await store.save_evidence(
                tool_name=tool_name,
                tool_args=tool_args,
                content=f"EXECUTION FAILED (Missing Dependencies):\n{deps_str}\nOriginal Error: {str(e)}",
                summary=f"Failed to run {tool_name}: Missing dependencies."
            )
            # We don't return immediately, we try recovery. 
            # But we must add this to the list we effectively return/accumulation logic.
            # We'll accumulate 'new_evidence_for_this_turn' locally if we want, 
            # but simpler: just append to a list we build.
            
            # Let's fix the variable scope. We need to append to `current_evidence`.
            current_evidence = state.get("evidence_refs", [])
            # We will append fail_snapshot to current_evidence shortly.
            
            # --- INTERNAL RECOVERY LOOP ---
            # Attempt to resolve the blocker immediately by running a Discovery Tool.
            logger.info(f"Investigator: Attempting in-flight resolution for blockers.")
            
            try:
                # 1. Select Resolution Tool
                resolution_context = f"""
                Problem: Tool '{tool_name}' failed.
                Missing Info:
                {deps_str}
                Source Hint: {e.suggested_source}
                
                Task: Select a DIFFERENT tool to FETCH this missing information immediately.
                """
                
                resolution_tools = await _select_resolution_tool(llm, None, resolution_context) # Component is implicit in context
                
                if resolution_tools:
                    res_tool_def = resolution_tools[0]
                    res_tool_name = res_tool_def["name"]
                    res_tool_args = res_tool_def["args"]
                    
                    logger.info(f"Investigator: Recovery - Executing resolution tool {res_tool_name}")
                    
                    # 2. Execute Resolution Tool
                    res_tool = CapabilityRegistry.get_tool(res_tool_name)
                    if res_tool:
                        res_output = await executor.execute(res_tool, res_tool_args, context)
                        
                        # 3. Save Resolution Evidence
                        res_snapshot = await store.save_evidence(
                            tool_name=res_tool_name,
                            tool_args=res_tool_args,
                            content=res_output,
                            summary=f"Resolution for blocker in {tool_name}"
                        )
                        
                        current_evidence = state.get("evidence_refs", [])
                        updated_evidence = current_evidence + [fail_snapshot, res_snapshot]
                        
                        # Return success with new evidence!
                        # The next iteration will pick up the original investigation, now unblocked.
                        return {
                            "evidence_refs": updated_evidence
                        }
            except Exception as res_e:
                 logger.error(f"Investigator: Recovery failed: {res_e}")

            # Fallback: Just save the Blocker Evidence if recovery failed/skipped
            snapshot = await store.save_evidence(
                tool_name="system_advisor",
                tool_args={"blocked_tool": tool_name, "missing": e.dependencies},
                content=f"EXECUTION BLOCKED.\nMissing Info:\n- {deps_str}\nSuggested Source: {e.suggested_source}\nRECOMMENDATION: Select a tool to discover this information.",
                summary=f"BLOCKED: Needed {len(e.dependencies)} inputs (e.g. {e.dependencies[0]}) to run {tool_name}."
            )
            
            # --- RAISE HITL SIGNAL ---
            # So the Human-In-The-Loop can prompt the user for missing info
            req = PendingRequirement(
                key=f"missing_{tool_name}_auto",
                description=f"{deps_str}",
                source_hint=e.suggested_source,
                tool_name=tool_name,
                component_id="unknown" # We don't enforce component ID matching tightly here
            )
            
            current_evidence = state.get("evidence_refs", [])
            updated_evidence = current_evidence + [fail_snapshot, snapshot]
            
            pending_requirements = state.get("pending_requirements", [])
            pending_requirements.append(req)
            
            return {
                "evidence_refs": updated_evidence,
                "pending_requirements": pending_requirements
            }

        except Exception as e:
            logger.error(f"Investigator: Execution failed: {e}")
            # Capture failure as evidence
            fail_snapshot = await store.save_evidence(
                tool_name=tool_name,
                tool_args=tool_args,
                content=f"EXECUTION FAILED: {str(e)}",
                summary=f"Failed to run {tool_name}: {str(e)[:100]}"
            )
            current_evidence = state.get("evidence_refs", [])
            updated_evidence = current_evidence + [fail_snapshot]
            return {
                "evidence_refs": updated_evidence
            }
    return {}

async def _select_resolution_tool(llm, component, context_str) -> List[Dict[str, Any]]:
    """
    Helper to select a tool to resolve missing info.
    (Duplicated/Shared logic with EvidenceCollector)
    """
    prompt = f"""
    Context: {context_str}
    
    Task: Select ONE read-only tool to retrieve the missing information.
    Return JSON: [ {{ "name": "tool", "args": {{ ... }} }} ]
    """
    try:
         # Search specifically for "info" or "status" or "list"
         found = CapabilityRegistry.search_tools("status info list get", limit=10)
         tools_json = json.dumps([{'name': t.name, 'description': t.description} for t in found])
         
         full_prompt = prompt + f"\nChoose from:\n{tools_json}"
         
         response = await llm.ainvoke([
             SystemMessage(content="You are a Recovery Specialist."), 
             HumanMessage(content=full_prompt)
         ])
         selection = json.loads(response.content.strip().replace("```json", "").replace("```", ""))
         if isinstance(selection, dict): return [selection]
         return selection
    except:
         return []
