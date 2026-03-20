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
from src.core.langfuse_integration import langfuse_manager, get_current_span, LangfuseManager

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
        self.llm = LLMFactory.get_model_for_agent("adaptive_fix")

    async def execute(self, tool: MCPToolInterface, args: Dict[str, Any], context: str = "", intent: str = "") -> str:
        """
        Execute a tool with adaptive logic.
        """
        tool_name = tool.name
        current_args = args.copy()
        attempts = 0
        last_error = None

        # Create Langfuse span for this tool execution
        parent_span = get_current_span()
        tool_span = langfuse_manager.create_span(
            parent=parent_span, name=f"tool:{tool_name}",
            input={"args": args}, metadata={"customer_id": self.customer_id},
        ) if parent_span else None

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

                LangfuseManager.end_span(tool_span, output={"result_length": len(str(result))})

                return result

            except Exception as e:
                attempts += 1
                last_error = e
                logger.warning(f"AdaptiveExec: {tool_name} failed (Attempt {attempts}/{self.max_retries+1}): {e}")

                if attempts > self.max_retries:
                    logger.error(f"AdaptiveExec: Max retries reached for {tool_name}")
                    LangfuseManager.end_span(
                        tool_span, output={"error": str(e)},
                        level="ERROR", status_message=str(e)[:200],
                    )
                    raise e # Re-raise final exception

                # 2. Heal / Diagnose
                try:
                    fixed_args = await self._diagnose_and_fix(tool, current_args, str(e), context, intent)

                    if not fixed_args:
                         logger.warning("AdaptiveExec: Diagnosis yielded no fix. Aborting retries.")
                         raise e

                    current_args = fixed_args

                except MissingDependencyError:
                    raise # Allow signal to bubble up to EvidenceCollector without logging error

                except Exception as diag_e:
                    logger.error(f"AdaptiveExec: Diagnosis failed: {diag_e}")
                    raise e



    async def _diagnose_and_fix(self, tool: MCPToolInterface, bad_args: Dict[str, Any], error_msg: str, context: str, intent: str = "") -> Optional[Dict[str, Any]]:
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

        missing_info_fmt = '{"missing_info": ["what is needed"], "suggested_source": "where to find it"}'
        return_fmt = '{"args": {...}, "reasoning": "one sentence"}'

        prompt = (
            "Tool: " + tool.name + "\n"
            "Description: " + (tool.description or "") + "\n"
            "Schema: " + json.dumps(schema) + "\n"
            "\n"
            "Failed args: " + json.dumps(bad_args, default=str) + "\n"
            "Error: " + error_msg + "\n"
            "\n"
            + (f"INTENT: {intent}\n\n" if intent else "")
            + "Context: " + context + "\n"
            "\n"
            + past_insights_text + "\n"
            "\n"
            "Fix the arguments. Common patterns:\n"
            "- If a value's format doesn't match what the schema expects, transform it (e.g. extract a singular identifier from an aggregate notation)\n"
            "- Fix parameter type mismatches against the schema\n"
            "- Component IDs are MCP identifiers -- do NOT try to resolve them to IPs\n"
            "\n"
            "Rules:\n"
            "- Only use data from context above. Do NOT invent values.\n"
            "- If past fixes are shown, use them as PATTERN guidance only -- never copy concrete values from past cases.\n"
            "- If you genuinely cannot fix it, return: " + missing_info_fmt + "\n"
            "\n"
            "Return JSON: " + return_fmt
        )

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
                     if isinstance(result_json, dict) and "reasoning" not in result_json:
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
             insight_prompt = (
                 "Tool: " + tool_name + "\n"
                 "Error: " + error_msg + "\n"
                 "Bad Args: " + json.dumps(original_args, default=str) + "\n"
                 "Fixed Args: " + json.dumps(fixed_args, default=str) + "\n"
                 "\n"
                 "Task: Summarize the Learning Rule in one sentence.\n"
                 'Example: "When getting status, use device parameter instead of target."'
             )

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
