from typing import Any, Dict, List
from src.core.models import GlobalState, Hypothesis, PendingRequirement, ToolSelectionContext
from src.core.registry import CapabilityRegistry
from src.core.evidence_store import EvidenceStore
from src.core.safety import is_safe_tool, is_tool_allowed_for_tenant
from src.core.tool_selector import ToolSelector
from src.core.adaptive_executor import AdaptiveExecutor, MissingDependencyError
from src.utils.state_formatters import (
    format_path_analysis,
    format_evidence_summaries,
)
import logging
import json
import hashlib

logger = logging.getLogger(__name__)


def _args_signature(tool_args: dict) -> str:
    """Deterministic hash of tool arguments for dedup."""
    normalized = json.dumps(tool_args or {}, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


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

    store = EvidenceStore(
        customer_id=state.get("customer_id", "unknown"),
        run_id=state.get("meta", {}).get("run_id")
    )

    # Build dedup set from prior invocations + existing evidence_refs
    existing_evidence = state.get("evidence_refs", [])
    _sig_list: List[str] = state.get("_executed_tool_signatures", [])
    executed_signatures: set = set(_sig_list)
    for ev in existing_evidence:
        executed_signatures.add(f"{ev.tool_name}::{_args_signature(ev.tool_args)}")

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
    selections = await selector.select_tools(ctx, max_intents=3)

    # Resolve prerequisite tools for selections with missing params
    selections, prereq_evidence = await selector.resolve_prerequisites(
        selections, components, state, store, executed_signatures
    )
    if prereq_evidence:
        existing_evidence = list(state.get("evidence_refs", [])) + prereq_evidence

    # Drop tools still missing params after resolution
    fully_bound = [s for s in selections if not s.missing_params]
    for s in selections:
        if s.missing_params:
            logger.warning(f"Investigator: Dropping {s.name} — still missing: {list(s.missing_params.keys())}")
    selections = fully_bound

    if not selections:
        logger.warning("Investigator: ToolSelector returned no tools.")
        if active_question:
            updated_questions = [
                q.model_copy(update={"status": "blocked", "answer": "No diagnostic tools available for this question."})
                if q.id == active_question.id else q
                for q in open_questions
            ]
            return {"open_questions": updated_questions}
        return {}

    # 4. Execute tools (highest priority first)
    for sel in selections:
        tool_name = sel.name
        tool_args = sel.args

        # DEDUP CHECK
        sig = f"{tool_name}::{_args_signature(tool_args)}"
        if sig in executed_signatures:
            logger.info(f"Investigator: SKIP duplicate {tool_name} (same args already executed)")
            continue

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
            executed_signatures.add(sig)

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
                "_executed_tool_signatures": list(executed_signatures),
            }
            if active_question:
                result["open_questions"] = updated_questions
            return result

        except MissingDependencyError as e:
            deps_str = "; ".join(e.dependencies)
            logger.warning(f"Investigator: Blocked by missing runtime dependency: {deps_str}")

            # Save ONE failure snapshot
            fail_snapshot = await store.save_evidence(
                tool_name=tool_name, tool_args=tool_args,
                content=f"RUNTIME DEPENDENCY ERROR:\n{deps_str}\nSource hint: {e.suggested_source}",
                summary=f"Failed {tool_name}: missing runtime dependency"
            )

            # Attempt runtime resolution via ToolSelector pipeline
            target_comp = best_comp or (components[0] if components else None)
            resolved_args, res_evidence = await selector.resolve_runtime_dependency(
                tool_name, tool_args, e, target_comp, components,
                state, store, executed_signatures,
            )
            resolution_evidence = [fail_snapshot] + res_evidence

            if resolved_args:
                # Retry original tool with resolved args (max 1 attempt)
                try:
                    retry_output = await executor.execute(tool, resolved_args, context, intent=sel.evaluation.reasoning)
                    snapshot = await store.save_evidence(
                        tool_name=tool_name, tool_args=resolved_args,
                        content=retry_output,
                        summary=f"Retry verification for: {target_hypothesis.summary}"
                    )
                    executed_signatures.add(f"{tool_name}::{_args_signature(resolved_args)}")

                    # Same state update as normal success path
                    updated_hypotheses = [
                        h.model_copy(update={"status": "verifying", "evidence_refs": list(h.evidence_refs) + [snapshot.id]})
                        if h.id == target_hypothesis.id else h
                        for h in hypotheses
                    ]
                    current_evidence = state.get("evidence_refs", [])
                    updated_evidence = current_evidence + resolution_evidence + [snapshot]

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
                        "_executed_tool_signatures": list(executed_signatures),
                    }
                    if active_question:
                        result["open_questions"] = updated_questions
                    return result

                except Exception as retry_e:
                    logger.warning(f"Investigator: Runtime recovery retry failed: {retry_e}")

            # Fallback: PendingRequirement (HITL)
            comp_id = target_comp.id if target_comp else "unknown"
            req = PendingRequirement(
                key=f"missing_{tool_name}_{comp_id}",
                description=deps_str,
                source_hint=e.suggested_source,
                tool_name=tool_name,
                component_id=comp_id,
            )
            current_evidence = state.get("evidence_refs", [])
            pending_requirements = state.get("pending_requirements", [])
            pending_requirements.append(req)

            return {
                "evidence_refs": current_evidence + resolution_evidence,
                "pending_requirements": pending_requirements,
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


