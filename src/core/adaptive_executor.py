from typing import Any, Dict, List, Optional
import logging
import json
import asyncio
from datetime import datetime

from src.core.interfaces import MCPToolInterface
from src.core.llm import LLMFactory
from src.core.qdrant import vector_store
from src.core.models import ToolKnowledge
from langchain_core.messages import SystemMessage, HumanMessage
from src.config import settings

logger = logging.getLogger(__name__)

class MissingDependencyError(Exception):
    """Raised when AdaptiveExecutor identifies specific missing information."""
    def __init__(self, dependencies: List[str], suggested_source: str):
        self.dependencies = dependencies # List of descriptions
        self.suggested_source = suggested_source
        msg = "; ".join(dependencies)
        super().__init__(f"Missing: {msg} (Ask: {suggested_source})")

class AdaptiveExecutor:
    """
    Executes tools with built-in:
    1. Knowledge Retrieval (Injection)
    2. Auto-Healing (Retry with LLM diagnosis)
    3. Continuous Learning (Save insights)
    """

    def __init__(self, max_retries: int = None, customer_id: str = "unknown"):
        if max_retries is None:
            self.max_retries = 1 if settings.TEST_MODE_FAST else 2
        else:
            self.max_retries = max_retries

        self.customer_id = customer_id
        self.llm = LLMFactory.get_model_for_agent("hypothesis") # Use fast model for diagnosis

    async def execute(self, tool: MCPToolInterface, args: Dict[str, Any], context: str = "") -> str:
        """
        Execute a tool with adaptive logic.
        """
        tool_name = tool.name
        current_args = args.copy()
        attempts = 0
        last_error = None
        
        # 1. Execution Loop
        while attempts <= self.max_retries:
            try:
                # Try Execution
                logger.debug(f"AdaptiveExec: Running {tool_name} (Attempt {attempts+1}) args={current_args}")
                result = await tool.run(**current_args)
                
                # Check for "Soft Failures" (Tool runs but returns error message text)
                # This is common in CLI tools that don't raise exceptions but print "Error: ..."
                if result and isinstance(result, str) and len(result) < 500:
                    lower_res = result.lower()
                    if "error" in lower_res or "fail" in lower_res or "invalid" in lower_res or "unknown" in lower_res:
                         # Treat as exception
                         raise Exception(f"Tool returned error message: {result}")

                # Success!
                if attempts > 0:
                    # If we succeeded after retries, we LEARN.
                    await self._learn_from_recovery(tool_name, args, current_args, last_error, str(last_error))
                
                return result

            except Exception as e:
                attempts += 1
                last_error = e
                logger.warning(f"AdaptiveExec: {tool_name} failed (Attempt {attempts}/{self.max_retries+1}): {e}")
                
                if attempts > self.max_retries:
                    logger.error(f"AdaptiveExec: Max retries reached for {tool_name}")
                    raise e # Re-raise final exception
                
                # 2. Heal / Diagnose
                try:
                    fixed_args = await self._diagnose_and_fix(tool, current_args, str(e), context)
                    
                    if not fixed_args:
                         logger.warning("AdaptiveExec: Diagnosis yielded no fix. Aborting retries.")
                         raise e
                    
                    current_args = fixed_args
                         
                except MissingDependencyError:
                    raise # Allow signal to bubble up to EvidenceCollector without logging error
                    
                except Exception as diag_e:
                    logger.error(f"AdaptiveExec: Diagnosis failed: {diag_e}")
                    raise e



    async def _diagnose_and_fix(self, tool: MCPToolInterface, bad_args: Dict[str, Any], error_msg: str, context: str) -> Optional[Dict[str, Any]]:
        """
        Ask LLM to fix the arguments based on the error.
        """
        schema = tool.args_schema.model_json_schema() if tool.args_schema else {}
        
        # RAG: Retrieve past insights for this tool/error (tenant-scoped, context-enriched query)
        past_insights_text = ""
        try:
             # Enrich search query with tool name + context for more scenario-specific embeddings
             search_query = f"tool:{tool.name} {context[:200]} error:{error_msg}" if context else error_msg
             insights = await vector_store.get_adaptive_fixes(
                 tool.name, error_msg=search_query, customer_id=self.customer_id, limit=2
             )
             if insights:
                 fix_lines = []
                 for i in insights:
                     line = f"- Insight: {i.get('insight', 'N/A')}"
                     fix = i.get('fix', {})
                     if fix:
                         line += f"\n  Bad args: {fix.get('bad', 'N/A')}"
                         line += f"\n  Good args: {fix.get('good', 'N/A')}"
                     fix_lines.append(line)
                 past_insights_text = "PAST SUCCESSFUL FIXES (from similar errors on this tenant):\n" + "\n".join(fix_lines)
        except Exception as e:
             logger.warning(f"AdaptiveExec: RAG retrieval failed: {e}")

        prompt = f"""
        SECTION: TOOL PARAMETER GROUNDING (MANDATORY)

        Goal: When repairing a failed MCP tool call, you MUST produce parameters grounded in real, case-related data. Never fabricate values to “make the tool succeed”.

        Hard Rules:
        1) NO FABRICATION
        - You may NOT invent: device names, interfaces, addresses, ports, identifiers, object names, credentials, paths, resource names, etc.
        - If a value is unknown, mark it unknown.

        2) EVERY PARAMETER MUST HAVE PROVENANCE
        For each parameter you propose, you must be able to answer internally:
        - “Where did this exact value come from?”
        If you cannot, you must NOT use it.

        3) VALIDATE BEFORE CALLING
        Before retrying a tool call, validate that each parameter matches tool schema and known context.

        4) SEMANTIC TYPE CHECKING (Identifiers vs Values)
        - Distinguish Identifiers from Addresses: If a tool requires a real address, hostname, or resource identifier, but the parameter provided is an abstract Inventory Identifier (e.g. "device_id", "asset_name"), DO NOT USE THE IDENTIFIER AS THE VALUE.
        - Resolution: You must RESOLVE the identifier to its actual value using Source S2 (Inventory) or S5 (Discovery).
        - Prohibition: NEVER substitute a random or placeholder value just to make the tool work.
        - Failure: If you cannot resolve the value, return OPTION B (Missing Info).

        Sources of Truth (ordered):
        S1) Current case payload / user-provided facts (explicit)
        S2) Client inventory (CMDB / inventory snapshot / “device facts” dataset)
        S3) Previous tool outputs from this same case (successful tool calls)
        S4) Deterministic derivations from S1–S3 (e.g., IP ∈ subnet → interface)
        S5) Discovery via dedicated read-only tools (e.g. list resources, describe components, show configuration, get status)

        Repair Loop (how you operate after a tool error):
        A) Classify failure cause (Schema, Missing param, Invalid value, Wrong scope, etc.)
        B) Identify which parameter(s) are suspect and why.
        C) Rebuild ONLY the suspect parameter(s) using Sources of Truth.
        D) Validate (Existence, Consistency).
        E) Retry with corrected parameters.
        
        CRITICAL: IF YOU CANNOT GROUND THE VALUE:
        Do NOT return guessed arguments. Instead, return a JSON requesting the missing info.

        Output Formats:
        
        OPTION A (Fix Found):
        {{
            "args": {{ "key": "value" }},
            "reasoning": "Fixed X based on inventory S2..."
        }}
        
        OPTION B (Missing Info - Grounding Failed):
        {{
            "missing_info": ["Description of missing param 1", "Description of missing param 2"],
            "suggested_source": "Who/What tool has this? (e.g. 'User', 'Discovery Tool')"
        }}

        Grounding Checks (generic invariants):
        - device/host: must match a real identifier in inventory.
        - scope/tenant/context: must match the case’s scope.
        - resource_name/endpoint/interface: must exist on the selected component.
        - source/destination addresses: must be real values from the case.
        
        ---------------------------------------------------------
        
        Context: {context}
        Tool: {tool.name}
        Description: {tool.description}
        Schema: {json.dumps(schema)}
        
        FAILED Arguments: {json.dumps(bad_args, default=str)}
        Error Message: {error_msg}
        
        {past_insights_text}
        
        Task: Diagnose the error and fix the arguments OR request missing info.
        
        CRITICAL INSTRUCTIONS:
        1. If 'PAST SUCCESSFUL FIXES' are provided above, evaluate each one:
           - Compare the failure PATTERN (error type, parameter structure) against the current error.
           - DO NOT copy concrete values (IPs, FQDNs, hostnames, resource names, UUIDs) from past fixes into the current fix. Those values belonged to a different case.
           - Treat past fixes as PATTERN EXAMPLES showing which parameters to change and how, NOT as literal value sources.
           - Only adopt a past fix's approach if the failure pattern genuinely matches.
        2. Diagnosis: Look at the Error Message. What is wrong? (Missing param, wrong type, invalid value?)
        3. Grounding Step: Attempt to rebuild suspect parameters using ONLY Sources of Truth (current case context, not past fix values).
        4. Decision:
           - If fully grounded -> Return OPTION A.
           - If data missing -> Return OPTION B.
        
        Return ONLY valid JSON.
        """
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="You are an expert Tool Debugger. Fix the tool arguments or identify missing dependencies."),
                HumanMessage(content=prompt)
            ])
            text = response.content.strip()
            
            # --- Robust JSON Cleaning ---
            # Remove markdown code blocks
            if "```" in text:
                import re
                text = re.sub(r"```json\s*", "", text)
                text = re.sub(r"```", "", text)
            
            text = text.strip()
            
            # Try parsing
            try:
                result_json = json.loads(text)
            except json.JSONDecodeError:
                # Fallback: aggressive cleanup for common LLM syntax errors
                logger.warning(f"AdaptiveExec: JSON decode failed for '{text[:50]}...'. Attempting repair.")
                import re
                # Fix trailing commas in objects/lists
                text = re.sub(r",\s*}", "}", text)
                text = re.sub(r",\s*]", "]", text)
                # Ensure keys are quoted (simple heuristic)
                # text = re.sub(r"(\w+):", r'"\1":', text) # Risky if URL
                try:
                    result_json = json.loads(text)
                except:
                    logger.error("AdaptiveExec: JSON repair failed.")
                    return None

            # Check for Missing Info signal
            if "missing_info" in result_json:
                missing = result_json.get("missing_info")
                source = result_json.get("suggested_source", "Unknown")
                
                # Normalize to list
                deps = []
                if isinstance(missing, list):
                    deps = [str(x) for x in missing]
                elif isinstance(missing, str):
                    deps = [missing]
                else:
                    deps = ["Unknown missing dependency"]

                logger.info(f"AdaptiveExec: Cannot fix. Missing info: {deps} from {source}")
                raise MissingDependencyError(deps, source)
            
            # Normal fix path
            new_args = result_json.get("args")
            if not new_args:
                 # Fallback for legacy simple JSON output if model didn't follow strict dict
                 if "args" not in result_json and "missing_info" not in result_json:
                     # Maybe it returned just the args?
                     if isinstance(result_json, dict) and not "reasoning" in result_json:
                        new_args = result_json
                     else:
                        logger.warning("AdaptiveExec: LLM returned unstructured JSON.")
                        return None
            
            logger.info(f"AdaptiveExec: Diagnosis suggests fix: {new_args}")
            return new_args
            
        except MissingDependencyError:
            raise # Propagate up
        except Exception as e:
            logger.error(f"AdaptiveExec: LLM Diagnosis failed: {e}")
            return None

    async def _learn_from_recovery(self, tool_name: str, original_args: Dict[str, Any], fixed_args: Dict[str, Any], error: Exception, error_msg: str):
        """
        Save the learned correction to Knowledge Base.
        """
        try:
             # Formulate the "Insight"
             # We could ask LLM to summarize, but for speed, let's just record the diff or error pattern.
             
             insight_prompt = f"""
             Tool: {tool_name}
             Error: {error_msg}
             Bad Args: {json.dumps(original_args, default=str)}
             Fixed Args: {json.dumps(fixed_args, default=str)}
             
             Task: Summarize the "Learning Rule" in one sentence.
             Example: "When getting status, use 'device' parameter instead of 'target'."
             """
             
             response = await self.llm.ainvoke([
                SystemMessage(content="You are a Knowledge Engineer."),
                HumanMessage(content=insight_prompt)
            ])
             insight_text = response.content.strip()
             
             knowledge = ToolKnowledge(
                 tool_name=tool_name,
                 error_pattern=str(error)[:100], # First 100 chars
                 insight=insight_text,
                 good_example=fixed_args
             )
             
             # Save to general knowledge (optional, for Evidence Collector)
             await vector_store.save_tool_insight(knowledge, customer_id=self.customer_id)

             # Save to Dedicated Adaptive Fixes (for Self-Healing)
             # FIX: Ensure nested dicts are serialized strings to prevent Qdrant 400 Bad Request
             # Qdrant payload values must be simple types or lists, deeply nested user objects might check schema strictness.
             # Safest is to store complex args as JSON strings.
             await vector_store.save_adaptive_fix(
                 tool_name=tool_name,
                 error_msg=error_msg,
                 insight=insight_text,
                 fix_data={
                     "bad": json.dumps(original_args, default=str),
                     "good": json.dumps(fixed_args, default=str)
                 },
                 customer_id=self.customer_id
             )
             
             logger.info(f"AdaptiveExec: LEARNED new insight for {tool_name}: {insight_text}")
             
        except Exception as e:
            logger.error(f"AdaptiveExec: Failed to save learning: {e}")
