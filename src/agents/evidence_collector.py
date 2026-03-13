from typing import Any, Dict, List
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re

from src.core.models import (
    GlobalState, EvidenceSnapshot, Component, PendingRequirement,
    ToolSelectionContext,
)
from src.core.registry import CapabilityRegistry
from src.core.evidence_store import EvidenceStore
from src.core.llm import LLMFactory
from src.core.safety import is_safe_tool, is_tool_allowed_for_tenant
from src.core.tool_selector import ToolSelector
from src.core.adaptive_executor import AdaptiveExecutor, MissingDependencyError
from src.utils.arg_sanitizer import sanitize_tool_args, is_executor_role, is_target_role
import logging

logger = logging.getLogger(__name__)


async def evidence_collector_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Collects evidence using centralized ToolSelector pipeline.
    """
    ticket_text = state["ticket"].text
    components = state.get("components", [])
    evidence_refs: List[EvidenceSnapshot] = state.get("evidence_refs", [])
    customer_id = state.get("customer_id", "unknown")

    logger.info(f"Evidence Collector: Processing {len(components)} components.")

    store = EvidenceStore(
        customer_id=customer_id,
        run_id=state.get("meta", {}).get("run_id")
    )
    llm = LLMFactory.get_model_for_agent("evidence_collector")

    new_evidence = []
    missing_info_list = []
    pending_requirements = []

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

    # --- RELATIONAL EVIDENCE PRE-LOOP ---
    relational_evidence = await _collect_relational_evidence(
        state, store, components, ticket_text, customer_id,
    )
    new_evidence.extend(relational_evidence)

    # --- PER-COMPONENT EVIDENCE LOOP ---
    for comp in components:
        try:
            # 1. Select tools via centralized ToolSelector pipeline
            selector = ToolSelector(customer_id=customer_id)
            ctx = ToolSelectionContext(
                ticket_text=ticket_text,
                component=comp,
                components=components,
                facts=state.get("facts", {}),
                path_context=path_context,
                mode="evidence",
            )
            selections = await selector.select_tools(ctx, max_tools=5)

            if not selections:
                logger.warning(f"No tools selected for {comp.id}.")
                continue

            # 2. Execute all selected tools
            for sel in selections:
                tool_name = sel.name
                tool_args = sel.args

                tool = CapabilityRegistry.get_tool(tool_name)
                if not tool:
                    logger.warning(f"Tool {tool_name} not found in registry.")
                    continue

                # SAFETY CHECK
                if not is_safe_tool(tool_name, tool_args):
                    logger.warning(f"Skipping unsafe tool execution: {tool_name}")
                    continue

                # GOVERNANCE CHECK
                if not await is_tool_allowed_for_tenant(tool_name, customer_id):
                    logger.warning(f"Skipping tool {tool_name}: not allowed for tenant {customer_id}")
                    continue

                # Type-aware argument injection (shared sanitizer)
                tool_args = sanitize_tool_args(tool_args, comp)

                logger.info(f"Evidence Collector: Executing {tool_name} with {tool_args}")
                try:
                    executor = AdaptiveExecutor(customer_id=customer_id)
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

                    logger.info(f"Attempting in-flight resolution for {deps_str}")

                    resolution_context = f"""
                    Problem: Tool '{tool_name}' failed on component '{comp.id}'.
                    Missing: {deps_str}
                    Source Hint: {missing_e.suggested_source}

                    Task: Select a DIFFERENT tool to FETCH this missing information from the component itself (or inventory).
                    Ex: If IP is missing, run 'get_system_interface' or similar.
                    """

                    try:
                        resolution_tools = await _select_resolution_tool(llm, comp, resolution_context)

                        if resolution_tools:
                            res_tool_def = resolution_tools[0]
                            res_tool_name = res_tool_def["name"]
                            res_tool_args = res_tool_def["args"]

                            if "device" in res_tool_args and is_executor_role(comp.role):
                                res_tool_args["device"] = comp.id

                            logger.info(f"Recovery: Executing resolution tool {res_tool_name}")

                            res_tool = CapabilityRegistry.get_tool(res_tool_name)
                            if res_tool:
                                res_output = await executor.execute(res_tool, res_tool_args, context)

                                res_snapshot = await store.save_evidence(
                                    tool_name=res_tool_name,
                                    tool_args=res_tool_args,
                                    content=res_output,
                                    summary=f"Resolution for {deps_str}"
                                )
                                new_evidence.append(res_snapshot)
                                logger.info(f"Recovery successful: Collected info via {res_tool_name}")
                                continue

                    except Exception as res_e:
                        logger.error(f"Recovery failed: {res_e}")

                    req = PendingRequirement(
                        key=f"missing_{tool_name}_{comp.id}",
                        description=deps_str,
                        source_hint=missing_e.suggested_source,
                        tool_name=tool_name,
                        component_id=comp.id
                    )
                    pending_requirements.append(req)
                    missing_info_list.append(f"{deps_str} ({comp.id})")
                    continue

                except Exception as e:
                    logger.error(f"Tool execution failed {tool_name}: {e}")
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
        "pending_requirements": pending_requirements,
        "case_status": "investigating",
    }


# Relational keywords that indicate src->dst queries are needed
_RELATIONAL_KEYWORDS = re.compile(
    r"\b(reach|connect|between|from\s+\S+\s+to|path|route|flow|"
    r"reachability|connectivity|communicate|access|traverse|forward|nat)\b",
    re.IGNORECASE,
)

_RELATIONAL_DOMAINS = frozenset([
    "connectivity", "reachability", "routing", "firewall", "network",
    "nat", "vpn", "tunnel", "forwarding",
])


def _is_relational_ticket(ticket_text: str, classification_domains: List[str]) -> bool:
    """Return True if the ticket involves relational (src->dst) concerns."""
    if any(d.lower() in _RELATIONAL_DOMAINS for d in classification_domains):
        return True
    return bool(_RELATIONAL_KEYWORDS.search(ticket_text))


async def _collect_relational_evidence(
    state: GlobalState,
    store: "EvidenceStore",
    components: List[Component],
    ticket_text: str,
    customer_id: str,
) -> List[EvidenceSnapshot]:
    """
    Relational pre-loop: pair source and target components, use ToolSelector
    in relational mode, and execute relational tools.
    """
    classification = state.get("classification")
    domains = classification.domains if classification else []

    if not _is_relational_ticket(ticket_text, domains):
        return []

    if len(components) < 2:
        return []

    logger.info("[Relational] Ticket has relational concerns — starting cross-component evidence collection.")

    # Split into sources (executors) and targets
    sources = [c for c in components if is_executor_role(c.role)]
    targets = [c for c in components if is_target_role(c.role)]

    pairs: List[tuple] = []
    if sources and targets:
        for src in sources:
            for tgt in targets:
                pairs.append((src, tgt))
    else:
        for i in range(len(components) - 1):
            pairs.append((components[i], components[i + 1]))

    pairs = pairs[:5]
    logger.info(f"[Relational] {len(pairs)} component pairs to evaluate.")

    new_evidence: List[EvidenceSnapshot] = []

    for src_comp, dst_comp in pairs:
        # Use ToolSelector in relational mode
        selector = ToolSelector(customer_id=customer_id)
        ctx = ToolSelectionContext(
            ticket_text=ticket_text,
            source_component=src_comp,
            target_component=dst_comp,
            components=components,
            mode="relational",
        )
        selections = await selector.select_tools(ctx, max_intents=2, max_tools=3)

        for sel in selections:
            t_name = sel.name
            tool_args = sel.args

            tool = CapabilityRegistry.get_tool(t_name)
            if not tool:
                continue

            if not is_safe_tool(t_name, tool_args):
                continue
            if not await is_tool_allowed_for_tenant(t_name, customer_id):
                continue

            # Sanitize with source (executor) for device-type args
            tool_args = sanitize_tool_args(tool_args, src_comp)
            # Sanitize with destination (target) for target-type args
            tool_args = sanitize_tool_args(tool_args, dst_comp)

            logger.info(f"[Relational] Executing {t_name} with {tool_args}")
            try:
                executor = AdaptiveExecutor(customer_id=customer_id)
                facts_str = json.dumps(state.get("facts", {}), default=str)
                context = (
                    f"Ticket: {ticket_text}\n"
                    f"Source: {src_comp.id} ({src_comp.role})\n"
                    f"Destination: {dst_comp.id} ({dst_comp.role})\n"
                    f"Goal: Relational evidence collection."
                )
                output = await executor.execute(tool, tool_args, context)

                snapshot = await store.save_evidence(
                    tool_name=t_name,
                    tool_args=tool_args,
                    content=output,
                    summary=f"Relational: {src_comp.id} -> {dst_comp.id}",
                )
                snapshot.tool_call_id = "relational"
                new_evidence.append(snapshot)
                logger.info(f"[Relational] Collected evidence with {t_name}")
            except Exception as e:
                logger.warning(f"[Relational] Execution failed for {t_name}: {e}")

            if len(new_evidence) >= 10:
                logger.info("[Relational] Reached max relational evidence cap (10).")
                return new_evidence

    logger.info(f"[Relational] Collected {len(new_evidence)} relational evidence snapshots.")
    return new_evidence


async def _select_resolution_tool(llm, component, context_str) -> List[Dict[str, Any]]:
    """Helper to select a tool to resolve missing info."""
    vendor = component.vendor or 'generic' if component else 'generic'
    prompt = f"""
    Context: {context_str}

    Available Tools (Heuristic): We need 'get', 'show', 'status', 'list' tools for {vendor}.

    Task: Select ONE read-only tool to retrieve the missing information.
    Return JSON: [ {{ "name": "tool", "args": {{ ... }} }} ]
    """
    try:
        found = CapabilityRegistry.search_tools("status info get", limit=10)
        tools_json = json.dumps([{'name': t.name, 'description': t.description} for t in found])

        full_prompt = prompt + f"\nChoose from:\n{tools_json}"

        response = await llm.ainvoke([SystemMessage(content="You are a Recovery Specialist."), HumanMessage(content=full_prompt)])
        return json.loads(response.content.strip().replace("```json", "").replace("```", ""))
    except Exception:
        return []
