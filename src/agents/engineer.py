"""Engineer agent — single-agent architecture for ticket investigation.

Replaces the 13-agent pipeline with one ReAct agent that has 6 meta-tools:
query_client_db, load_domain_skill, search_tool_catalog, search_knowledge_base,
execute_tool, and submit_findings.

The agent runs a continuous reasoning loop, naturally adapting its approach
based on ticket intent (incident, review, advisory, change). Structured
output is produced by the agent itself via submit_findings — no post-hoc
extraction needed.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from src.agents.engineer_prompts import ENGINEER_SYSTEM_PROMPT
from src.agents.engineer_tools import create_engineer_tools
from src.config import settings
from src.core.langfuse_integration import langfuse_manager, get_current_trace
from src.core.llm import LLMFactory
from src.core.models import (
    CaseStatus,
    Fact,
    GlobalState,
    Hypothesis,
    Plan,
    PlanStep,
    ScoringResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conversion helpers: raw dicts → GlobalState models
# ---------------------------------------------------------------------------

def _to_hypotheses(raw_list: List[dict]) -> List[Hypothesis]:
    result = []
    for i, h in enumerate(raw_list):
        result.append(Hypothesis(
            id=f"hyp_{uuid.uuid4().hex[:8]}",
            summary=h.get("summary", ""),
            confidence=float(h.get("confidence", 0.5)),
            rank=i + 1,
            status=h.get("status", "proposed"),
            evidence_refs=h.get("evidence_refs", []),
            rationale=h.get("rationale", ""),
        ))
    return result


def _to_facts(raw_list: List[dict]) -> List[Fact]:
    return [
        Fact(
            key=f.get("key", ""),
            value=f.get("value", ""),
            source_evidence_id=f.get("source_evidence_id", ""),
            confidence=float(f.get("confidence", 1.0)),
        )
        for f in raw_list
    ]


def _to_plan(raw: Optional[dict]) -> Optional[Plan]:
    if not raw:
        return None

    def convert_steps(steps: list) -> List[PlanStep]:
        return [
            PlanStep(
                step_id=f"step_{uuid.uuid4().hex[:6]}",
                description=s.get("description", ""),
                tool=s.get("tool", ""),
                args={},
                expected_outcome=s.get("expected_outcome", ""),
                risk=s.get("risk", "low"),
            )
            for s in steps
        ]

    return Plan(
        diagnosis_steps=convert_steps(raw.get("diagnosis_steps", [])),
        proposed_changes=convert_steps(raw.get("proposed_changes", [])),
        validation=convert_steps(raw.get("validation", [])),
        rollback=convert_steps(raw.get("rollback", [])),
    )


def _convert_findings(
    findings: dict,
) -> tuple[List[Hypothesis], List[Fact], Optional[Plan]]:
    """Convert submitted findings to models, degrading instead of failing.

    A malformed findings payload must never fail the run: at this point the
    investigation is already complete and the summary is the deliverable —
    losing it to a shape error in the structured extras is the worst outcome.
    """
    try:
        return (
            _to_hypotheses(findings.get("hypotheses", [])),
            _to_facts(findings.get("facts", [])),
            _to_plan(findings.get("plan")),
        )
    except Exception:
        logger.error(
            "Engineer: findings conversion failed — degrading to summary-only findings",
            exc_info=True,
        )
        return [], [], None


# ---------------------------------------------------------------------------
# Fallback: extract minimal findings from last AI message (no LLM call)
# ---------------------------------------------------------------------------

def _fallback_findings(messages: list, evidence_refs: List[str]) -> dict:
    """Build minimal findings when the agent didn't call submit_findings."""
    final_text = ""
    for msg in reversed(messages):
        if getattr(msg, "type", "") == "ai" and getattr(msg, "content", ""):
            final_text = msg.content
            break

    return {
        "summary": final_text or "Investigation completed but no structured findings were submitted.",
        "hypotheses": [],
        "facts": [],
        "plan": {},
        "case_status": "resolved",
        "evidence_refs": evidence_refs,
    }


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------

async def engineer_agent_node(state: GlobalState) -> Dict[str, Any]:
    """LangGraph node: Engineer agent with ReAct tool-calling loop."""
    customer_id = state.get("customer_id", "")
    meta = dict(state.get("meta", {}))
    run_id = meta.get("run_id", "")
    ticket = state.get("ticket")

    if not ticket:
        logger.error("Engineer: No ticket in state")
        return {"final_answer": "Error: No ticket provided.", "case_status": "blocked"}

    ticket_id = ticket.id

    logger.info(f"Engineer: Starting investigation for ticket {ticket_id} (customer={customer_id})")

    # 1. Create meta-tools with runtime context
    tools, tool_state = create_engineer_tools(
        customer_id=customer_id,
        run_id=run_id,
        ticket_id=ticket_id,
        max_tool_calls=settings.ENGINEER_MAX_TOOL_CALLS,
    )

    # 2. Build LLM
    llm = LLMFactory.get_model_for_agent("engineer")

    # 3. Create ReAct agent
    react_agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SystemMessage(content=ENGINEER_SYSTEM_PROMPT),
    )

    # 4. Format ticket input
    ticket_text = (
        f"# Ticket {ticket.id}\n"
        f"Mode: {ticket.mode}\n"
        f"Severity: {ticket.severity}\n"
        f"Source: {ticket.source}\n\n"
        f"{ticket.text}"
    )

    # 5. Build invocation config with Langfuse callback for full observability
    invoke_config = {"recursion_limit": settings.ENGINEER_MAX_ITERATIONS}
    langfuse_handler = langfuse_manager.get_callback_handler_for_span(
        get_current_trace(),
        metadata={"agent": "engineer", "ticket_id": ticket_id, "customer_id": customer_id},
    )
    if langfuse_handler:
        invoke_config["callbacks"] = [langfuse_handler]

    # 6. Run with timeout
    loop_error = None
    timed_out = False
    try:
        result = await asyncio.wait_for(
            react_agent.ainvoke(
                {"messages": [HumanMessage(content=ticket_text)]},
                config=invoke_config,
            ),
            timeout=settings.ENGINEER_TIMEOUT_SECONDS,
        )
        messages = result.get("messages", [])
    except asyncio.TimeoutError:
        logger.warning(f"Engineer: Timeout after {settings.ENGINEER_TIMEOUT_SECONDS}s for ticket {ticket_id}")
        messages = []
        timed_out = True
    except Exception as e:
        logger.error(f"Engineer: ReAct loop failed: {e}")
        messages = []
        loop_error = str(e)

    # 6. Read findings from tool state (set by submit_findings tool)
    if tool_state.findings:
        findings = tool_state.findings
        logger.info(f"Engineer: Findings submitted via submit_findings tool")
    elif loop_error:
        # Hard failure before any usable output: propagate so the run is
        # persisted as "failed" instead of "completed" with a blank report.
        raise RuntimeError(f"Engineer ReAct loop failed: {loop_error}")
    elif timed_out:
        findings = {
            "summary": (
                "## Investigation Interrupted\n\n"
                f"The investigation exceeded the {settings.ENGINEER_TIMEOUT_SECONDS}s time limit "
                "before findings could be submitted. "
                f"Evidence snapshots collected before the interruption: {len(tool_state.evidence_refs)}."
            ),
            "hypotheses": [],
            "facts": [],
            "plan": {},
            "case_status": "blocked",
            "evidence_refs": tool_state.evidence_refs,
        }
    else:
        logger.warning(f"Engineer: Agent did not call submit_findings — using fallback extraction")
        findings = _fallback_findings(messages, tool_state.evidence_refs)

    # 7. Convert to GlobalState models
    hypotheses, structured_facts, plan = _convert_findings(findings)
    facts_dict = {f.key: f.value for f in structured_facts}
    case_status = findings.get("case_status", "resolved")
    final_answer = findings.get("summary", "")
    if not isinstance(final_answer, str):
        final_answer = str(final_answer)

    # Build scoring result (synthetic, for frontend compatibility)
    scoring = ScoringResult(
        confidence=max((h.confidence for h in hypotheses), default=0.0),
        evidence_coverage=1.0 if tool_state.evidence_refs else 0.0,
        decision="proceed_to_plan" if case_status == "resolved" else "escalate_to_human",
        rationale="Single-agent investigation completed.",
    )

    # Update meta
    meta["iterations"] = 1
    meta["tool_calls"] = tool_state.tool_call_count
    meta["pipeline_mode"] = "engineer"

    logger.info(
        f"Engineer: Investigation complete for ticket {ticket_id}. "
        f"Tool calls: {tool_state.tool_call_count}, "
        f"Evidence: {len(tool_state.evidence_refs)}, "
        f"Hypotheses: {len(hypotheses)}, "
        f"Status: {case_status}"
    )

    return {
        "client_context": tool_state.client_context,
        "topology_nodes": tool_state.topology_nodes,
        "topology_edges": tool_state.topology_edges,
        "evidence_refs": tool_state.evidence_refs,
        "hypotheses": hypotheses,
        "structured_facts": structured_facts,
        "facts": facts_dict,
        "scoring": scoring,
        "plan": plan,
        "final_answer": final_answer,
        "case_status": case_status,
        "_executed_tool_signatures": tool_state.executed_signatures,
        "meta": meta,
    }
