from typing import Any, Dict, List
import json
import hashlib
import re

from src.core.models import (
    GlobalState, EvidenceSnapshot, Component, PendingRequirement,
    ToolSelectionContext,
)
from src.core.registry import CapabilityRegistry
from src.core.evidence_store import EvidenceStore
from src.core.safety import is_safe_tool, is_tool_allowed_for_tenant
from src.core.tool_selector import ToolSelector
from src.core.adaptive_executor import AdaptiveExecutor, MissingDependencyError
from src.core.models import is_executor_role, is_target_role
from src.utils.state_formatters import format_evidence_summaries
import logging

logger = logging.getLogger(__name__)


def _args_signature(tool_args: dict) -> str:
    """Deterministic hash of tool arguments for dedup."""
    normalized = json.dumps(tool_args or {}, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


async def evidence_collector_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Collects evidence using centralized ToolSelector pipeline.
    """
    ticket = state["ticket"]
    ticket_text = ticket.text
    components = state.get("components", [])
    evidence_refs: List[EvidenceSnapshot] = state.get("evidence_refs", [])
    customer_id = state.get("customer_id", "unknown")
    run_id = state.get("meta", {}).get("run_id")

    # Build dedup set from prior invocations + existing evidence_refs
    _sig_list: List[str] = state.get("_executed_tool_signatures", [])
    executed_signatures: set = set(_sig_list)
    for ev in evidence_refs:
        executed_signatures.add(f"{ev.tool_name}::{_args_signature(ev.tool_args)}")

    logger.info(f"Evidence Collector: Processing {len(components)} components ({len(executed_signatures)} tools already executed).")

    store = EvidenceStore(
        customer_id=customer_id,
        run_id=run_id,
        ticket_id=ticket.id,
    )

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
        executed_signatures=executed_signatures,
        run_id=run_id,
    )
    new_evidence.extend(relational_evidence)

    # --- PER-COMPONENT EVIDENCE LOOP ---
    for comp in components:
        try:
            # 1. Select tools via centralized ToolSelector pipeline
            selector = ToolSelector(customer_id=customer_id, run_id=run_id)
            evidence_context = format_evidence_summaries(
                evidence_refs + new_evidence, max_items=15
            )
            ctx = ToolSelectionContext(
                ticket_text=ticket_text,
                component=comp,
                components=components,
                facts=state.get("facts", {}),
                path_context=path_context,
                evidence_summaries=evidence_context,
                mode="evidence",
            )
            selections = await selector.select_tools(ctx)

            # Resolve prerequisite tools for selections with missing params
            selections, prereq_evidence = await selector.resolve_prerequisites(
                selections, components, state, store, executed_signatures
            )
            if prereq_evidence:
                new_evidence.extend(prereq_evidence)

            # Drop tools still missing params after resolution
            fully_bound = [s for s in selections if not s.missing_params]
            for s in selections:
                if s.missing_params:
                    logger.warning(f"EvidenceCollector: Dropping {s.name} — still missing: {list(s.missing_params.keys())}")
            selections = fully_bound

            if not selections:
                logger.warning(f"No tools selected for {comp.id}.")
                continue

            # 2. Execute all selected tools
            for sel in selections:
                tool_name = sel.name
                tool_args = sel.args

                # DEDUP CHECK
                sig = f"{tool_name}::{_args_signature(tool_args)}"
                if sig in executed_signatures:
                    logger.info(f"Evidence Collector: SKIP duplicate {tool_name} (same args already executed)")
                    continue

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

                logger.info(f"Evidence Collector: Executing {tool_name} with {tool_args}")
                try:
                    executor = AdaptiveExecutor(customer_id=customer_id, run_id=run_id)
                    facts_str = json.dumps(state.get("facts", {}), default=str)
                    meta_str = json.dumps(comp.metadata, default=str) if comp.metadata else "{}"
                    context = (
                        f"Ticket: {ticket_text}\n"
                        f"Component: {comp.id} (role={comp.role}, vendor={comp.vendor or 'unknown'})\n"
                        f"Component metadata: {meta_str}\n"
                        f"Facts: {facts_str}\nGoal: Collect evidence."
                    )

                    output = await executor.execute(tool, tool_args, context, intent=sel.evaluation.reasoning)

                    snapshot = await store.save_evidence(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        content=output
                    )
                    snapshot.tool_call_id = "auto"
                    new_evidence.append(snapshot)
                    executed_signatures.add(sig)
                    logger.info(f"Collected evidence with {tool_name}")

                except MissingDependencyError as missing_e:
                    deps_str = "; ".join(missing_e.dependencies)
                    logger.warning(f"AdaptiveExec Signal: Missing Info for {tool_name} -> {deps_str}")

                    # Save ONE failure snapshot
                    fail_snapshot = await store.save_evidence(
                        tool_name=tool_name, tool_args=tool_args,
                        content=f"RUNTIME DEPENDENCY ERROR: {deps_str}\nSource hint: {missing_e.suggested_source}",
                        summary=f"Failed {tool_name}: missing runtime dependency"
                    )
                    new_evidence.append(fail_snapshot)

                    # Attempt runtime resolution via ToolSelector pipeline
                    resolved_args, res_evidence = await selector.resolve_runtime_dependency(
                        tool_name, tool_args, missing_e, comp, components,
                        state, store, executed_signatures,
                    )
                    new_evidence.extend(res_evidence)

                    if resolved_args:
                        # Retry original tool with resolved args (max 1 attempt)
                        try:
                            retry_output = await executor.execute(tool, resolved_args, context, intent=sel.evaluation.reasoning)
                            retry_snapshot = await store.save_evidence(
                                tool_name=tool_name, tool_args=resolved_args,
                                content=retry_output,
                                summary=f"Retry after runtime resolution"
                            )
                            retry_snapshot.tool_call_id = "auto"
                            new_evidence.append(retry_snapshot)
                            executed_signatures.add(f"{tool_name}::{_args_signature(resolved_args)}")
                            logger.info(f"Runtime recovery successful: {tool_name}")
                            continue
                        except Exception as retry_e:
                            logger.warning(f"Runtime recovery retry failed for {tool_name}: {retry_e}")

                    # Fallback: PendingRequirement (HITL)
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
        "_executed_tool_signatures": list(executed_signatures),
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
    executed_signatures: set | None = None,
    run_id: str | None = None,
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
        selector = ToolSelector(customer_id=customer_id, run_id=run_id)
        ctx = ToolSelectionContext(
            ticket_text=ticket_text,
            source_component=src_comp,
            target_component=dst_comp,
            components=components,
            mode="relational",
        )
        selections = await selector.select_tools(ctx, max_intents=3)

        for sel in selections:
            t_name = sel.name
            tool_args = sel.args

            # DEDUP CHECK
            if executed_signatures is not None:
                sig = f"{t_name}::{_args_signature(tool_args)}"
                if sig in executed_signatures:
                    logger.info(f"[Relational] SKIP duplicate {t_name} (same args already executed)")
                    continue

            tool = CapabilityRegistry.get_tool(t_name)
            if not tool:
                continue

            if not is_safe_tool(t_name, tool_args):
                continue
            if not await is_tool_allowed_for_tenant(t_name, customer_id):
                continue

            logger.info(f"[Relational] Executing {t_name} with {tool_args}")
            try:
                executor = AdaptiveExecutor(customer_id=customer_id, run_id=run_id)
                src_meta = json.dumps(src_comp.metadata, default=str) if src_comp.metadata else "{}"
                dst_meta = json.dumps(dst_comp.metadata, default=str) if dst_comp.metadata else "{}"
                context = (
                    f"Ticket: {ticket_text}\n"
                    f"Source: {src_comp.id} (role={src_comp.role}, metadata={src_meta})\n"
                    f"Destination: {dst_comp.id} (role={dst_comp.role}, metadata={dst_meta})\n"
                    f"Goal: Relational evidence collection."
                )
                output = await executor.execute(tool, tool_args, context, intent=sel.evaluation.reasoning)

                snapshot = await store.save_evidence(
                    tool_name=t_name,
                    tool_args=tool_args,
                    content=output,
                    summary=f"Relational: {src_comp.id} -> {dst_comp.id}",
                )
                snapshot.tool_call_id = "relational"
                new_evidence.append(snapshot)
                if executed_signatures is not None:
                    executed_signatures.add(f"{t_name}::{_args_signature(tool_args)}")
                logger.info(f"[Relational] Collected evidence with {t_name}")
            except Exception as e:
                logger.warning(f"[Relational] Execution failed for {t_name}: {e}")

            if len(new_evidence) >= 10:
                logger.info("[Relational] Reached max relational evidence cap (10).")
                return new_evidence

    logger.info(f"[Relational] Collected {len(new_evidence)} relational evidence snapshots.")
    return new_evidence


