from typing import Any, Dict, List
from src.core.models import GlobalState, Hypothesis, PendingRequirement, ToolSelectionContext
from src.core.llm import LLMFactory
from src.core.registry import CapabilityRegistry
from src.core.evidence_store import EvidenceStore
from src.core.safety import is_safe_tool, is_tool_allowed_for_tenant
from src.core.tool_selector import ToolSelector
from src.core.adaptive_executor import AdaptiveExecutor, MissingDependencyError
from src.core.models import is_executor_role
from src.utils.state_formatters import (
    format_path_analysis,
    format_evidence_summaries,
)
from langchain_core.messages import SystemMessage, HumanMessage
import logging
import json

logger = logging.getLogger(__name__)


async def investigator_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Selects top hypothesis and executes specific verification tools.
    Uses centralized ToolSelector pipeline for tool selection.
    """
    hypotheses = state.get("hypotheses", [])
    open_questions = state.get("open_questions", [])

    # 1. Select Target Hypothesis
    candidates = [h for h in hypotheses if h.status in ["proposed", "verifying"]]
    candidates.sort(key=lambda x: (0 if x.status == "verifying" else 1, x.rank))

    if not candidates:
        logger.info("Investigator: No proposed hypotheses to verify.")
        return {}

    target_hypothesis = candidates[0]

    # 1b. Select the next open question to drive investigation (if available)
    active_question = None
    for q in open_questions:
        if q.status == "open":
            # Prefer questions linked to the target hypothesis
            if q.source_hypothesis_id == target_hypothesis.id:
                active_question = q
                break
    # Fallback: any open question
    if not active_question:
        for q in open_questions:
            if q.status == "open":
                active_question = q
                break

    question_context = ""
    if active_question:
        question_context = (
            f"\nInvestigation Question: {active_question.question}"
            f"\nWhy: {active_question.why}"
            f"\nDone when: {active_question.done_when}"
        )
        logger.info(f"Investigator: Targeting question [{active_question.id}]: {active_question.question}")

    logger.info(f"Investigator: Verifying Hypothesis (Rank {target_hypothesis.rank}): {target_hypothesis.summary}")

    llm = LLMFactory.get_model_for_agent("investigator")
    store = EvidenceStore(
        customer_id=state.get("customer_id", "unknown"),
        run_id=state.get("meta", {}).get("run_id")
    )

    # 2. Build context for ToolSelector
    customer_id = state.get("customer_id", "unknown")
    components = state.get("components", [])
    facts = state.get("facts", {})
    path_str = format_path_analysis(state.get("path_analysis"), max_breakpoints=5)
    evidence_context = format_evidence_summaries(state.get("evidence_refs", []), max_items=8)

    # Derive target component from hypothesis (best match from components)
    target_component = components[0] if components else None

    # 3. Use ToolSelector in investigation mode
    selector = ToolSelector(customer_id=customer_id)
    ctx = ToolSelectionContext(
        ticket_text=state["ticket"].text + question_context,
        component=target_component,
        components=components,
        hypothesis=target_hypothesis,
        facts=facts,
        path_context=path_str,
        evidence_summaries=evidence_context,
        mode="investigation",
    )
    selections = await selector.select_tools(ctx, max_intents=3, max_tools=5)

    if not selections:
        logger.warning("Investigator: ToolSelector returned no tools.")
        return {}

    # 4. Execute tools (highest priority first)
    for sel in selections:
        tool_name = sel.name
        tool_args = sel.args

        tool = CapabilityRegistry.get_tool(tool_name)
        if not tool:
            logger.warning(f"Investigator: Tool {tool_name} not found in registry.")
            continue

        # SAFETY CHECK
        if not is_safe_tool(tool_name, tool_args):
            logger.warning(f"Investigator: Skipping unsafe tool execution: {tool_name}")
            continue

        # GOVERNANCE CHECK
        if not await is_tool_allowed_for_tenant(tool_name, customer_id):
            logger.warning(f"Investigator: Tool {tool_name} not allowed for tenant {customer_id}")
            continue

        try:
            logger.info(f"Investigator: Executing {tool_name} with {tool_args}")

            executor = AdaptiveExecutor(customer_id=customer_id)
            facts_str = json.dumps(state.get("facts", {}), default=str)
            best_comp = next((c for c in components if c.id in str(tool_args.values())), components[0] if components else None)
            comp_meta = json.dumps(best_comp.metadata, default=str) if best_comp and best_comp.metadata else "{}"
            context = (
                f"Ticket: {state['ticket'].text}\n"
                f"Component: {best_comp.id if best_comp else 'unknown'} (metadata={comp_meta})\n"
                f"Facts: {facts_str}\n"
                f"Hypothesis: {target_hypothesis.summary}\nGoal: Verify hypothesis."
            )

            output = await executor.execute(tool, tool_args, context, intent=sel.evaluation.reasoning)

            snapshot = await store.save_evidence(
                tool_name=tool_name,
                tool_args=tool_args,
                content=output,
                summary=f"Verification for hypothesis: {target_hypothesis.summary}"
            )

            # Mark hypothesis as 'verifying' and link evidence
            updated_hypotheses = []
            for h in hypotheses:
                if h.id == target_hypothesis.id:
                    new_ev_refs = list(h.evidence_refs) + [snapshot.id]
                    updated_h = h.model_copy(update={
                        "status": "verifying",
                        "evidence_refs": new_ev_refs,
                    })
                    updated_hypotheses.append(updated_h)
                else:
                    updated_hypotheses.append(h)

            current_evidence = state.get("evidence_refs", [])
            updated_evidence = current_evidence + [snapshot]

            # Mark the active question as answered if one was targeted
            updated_questions = list(open_questions)
            if active_question:
                updated_questions = [
                    q.model_copy(update={"status": "answered", "answer": snapshot.summary})
                    if q.id == active_question.id else q
                    for q in updated_questions
                ]

            result: Dict[str, Any] = {
                "hypotheses": updated_hypotheses,
                "evidence_refs": updated_evidence,
                "case_status": "investigating",
            }
            if active_question:
                result["open_questions"] = updated_questions
            return result

        except MissingDependencyError as e:
            deps_str = "\n- ".join(e.dependencies)
            logger.warning(f"Investigator: Blocked by Missing Dependencies:\n- {deps_str}")

            fail_snapshot = await store.save_evidence(
                tool_name=tool_name,
                tool_args=tool_args,
                content=f"EXECUTION FAILED (Missing Dependencies):\n{deps_str}\nOriginal Error: {str(e)}",
                summary=f"Failed to run {tool_name}: Missing dependencies."
            )

            current_evidence = state.get("evidence_refs", [])

            # --- INTERNAL RECOVERY LOOP ---
            logger.info(f"Investigator: Attempting in-flight resolution for blockers.")

            try:
                resolution_context = f"""
                Problem: Tool '{tool_name}' failed.
                Missing Info:
                {deps_str}
                Source Hint: {e.suggested_source}

                Task: Select a DIFFERENT tool to FETCH this missing information immediately.
                """

                resolution_tools = await _select_resolution_tool(llm, None, resolution_context)

                if resolution_tools:
                    res_tool_def = resolution_tools[0]
                    res_tool_name = res_tool_def["name"]
                    res_tool_args = res_tool_def["args"]

                    logger.info(f"Investigator: Recovery - Executing resolution tool {res_tool_name}")

                    res_tool = CapabilityRegistry.get_tool(res_tool_name)
                    if res_tool:
                        res_output = await executor.execute(res_tool, res_tool_args, context)

                        res_snapshot = await store.save_evidence(
                            tool_name=res_tool_name,
                            tool_args=res_tool_args,
                            content=res_output,
                            summary=f"Resolution for blocker in {tool_name}"
                        )

                        current_evidence = state.get("evidence_refs", [])
                        updated_evidence = current_evidence + [fail_snapshot, res_snapshot]

                        return {
                            "evidence_refs": updated_evidence
                        }
            except Exception as res_e:
                logger.error(f"Investigator: Recovery failed: {res_e}")

            # Fallback: save blocker evidence
            snapshot = await store.save_evidence(
                tool_name="system_advisor",
                tool_args={"blocked_tool": tool_name, "missing": e.dependencies},
                content=f"EXECUTION BLOCKED.\nMissing Info:\n- {deps_str}\nSuggested Source: {e.suggested_source}\nRECOMMENDATION: Select a tool to discover this information.",
                summary=f"BLOCKED: Needed {len(e.dependencies)} inputs (e.g. {e.dependencies[0]}) to run {tool_name}."
            )

            req = PendingRequirement(
                key=f"missing_{tool_name}_auto",
                description=f"{deps_str}",
                source_hint=e.suggested_source,
                tool_name=tool_name,
                component_id="unknown"
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
    """Helper to select a tool to resolve missing info."""
    prompt = f"""
    Context: {context_str}

    Task: Select ONE read-only tool to retrieve the missing information.
    Return JSON: [ {{ "name": "tool", "args": {{ ... }} }} ]
    """
    try:
        found = CapabilityRegistry.search_tools("status info list get", limit=10)
        tools_json = json.dumps([{'name': t.name, 'description': t.description} for t in found])

        full_prompt = prompt + f"\nChoose from:\n{tools_json}"

        response = await llm.ainvoke([
            SystemMessage(content="You are a Recovery Specialist."),
            HumanMessage(content=full_prompt)
        ])
        selection = json.loads(response.content.strip().replace("```json", "").replace("```", ""))
        if isinstance(selection, dict):
            return [selection]
        return selection
    except Exception:
        return []
