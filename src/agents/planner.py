from typing import Any, Dict
from src.core.models import GlobalState, Plan, Hypothesis
from src.core.llm import LLMFactory
from src.retrieval.case_retriever import CaseRetriever
from src.core.qdrant import vector_store
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
import logging

logger = logging.getLogger(__name__)


async def _build_common_context(state: GlobalState) -> tuple:
    """Build facts, evidence, and CBR context shared by both planning paths."""
    ticket = state["ticket"]
    facts = state.get("facts", {})
    evidence_refs = state.get("evidence_refs", [])
    facts_summary = "\n".join(
        [f"- {k}: {v}" for k, v in facts.items() if not k.startswith("_")]
    ) or "No facts collected yet."
    evidence_summary_text = "\n".join(
        [f"- [{e.tool_name}]: {e.summary}" for e in evidence_refs[-10:]]
    ) or "No evidence gathered yet."

    cbr_context = ""
    try:
        retriever = CaseRetriever(vector_store)
        similar_cases = await retriever.retrieve_similar_cases(
            ticket, customer_id=state.get("customer_id", "unknown"), limit=3
        )
        cbr_context = retriever.format_cases_for_context(similar_cases)
    except Exception as e:
        logger.warning(f"Planner: CBR retrieval failed (proceeding without past cases): {e}")
        cbr_context = "No similar past cases available."

    return facts_summary, evidence_summary_text, cbr_context


async def _plan_from_goals(state: GlobalState) -> Dict[str, Any]:
    """Generate an implementation plan from fulfillment goals (change tickets)."""
    ticket = state["ticket"]
    goals = state.get("fulfillment_goals", [])

    goals_text = "\n".join(
        [f"- [{g.status}] {g.description}\n  Preconditions: {', '.join(g.preconditions) or 'none'}\n"
         f"  Validation: {', '.join(g.validation_criteria) or 'none'}\n"
         f"  Sub-goals: {', '.join(g.sub_goals) or 'none'}"
         for g in goals]
    ) or "No goals defined."

    logger.info(f"ResolutionPlanner: Building implementation plan from {len(goals)} fulfillment goals.")

    facts_summary, evidence_summary_text, cbr_context = await _build_common_context(state)

    llm = LLMFactory.get_model_for_agent("planner", temperature=0.0)
    parser = PydanticOutputParser(pydantic_object=Plan)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert IT Change Management Engineer planning implementation strategies.
Your goal is to create a safe, step-by-step Implementation Plan to fulfill the requested change.

GUIDELINES:
1. **Safety First**: Verify all preconditions before making changes. Do NOT skip validation steps.
2. **Diagnosis Steps**: Pre-checks to confirm preconditions are met and the environment is ready.
3. **Proposed Changes**: Implementation steps to fulfill each goal, ordered by dependency.
4. **Validation**: Steps to confirm each goal's validation criteria are satisfied.
5. **Rollback**: Steps to revert if the implementation fails or causes issues.
6. **Learn from History**: Review the 'Relevant Past Cases' below. If a similar change was executed before, prioritize those tools and steps.

Output must be valid JSON adhering to the schema.
"""),
        ("user", """### Context
**Ticket**: {ticket_text}

**Fulfillment Goals**:
{goals_text}

### Facts Already Collected
{facts_summary}

### Evidence Already Gathered
{evidence_summary}

{cbr_context}

{format_instructions}
""")
    ])

    chain = prompt | llm | parser

    try:
        plan = await chain.ainvoke({
            "ticket_text": ticket.text,
            "goals_text": goals_text,
            "facts_summary": facts_summary,
            "evidence_summary": evidence_summary_text,
            "cbr_context": cbr_context,
            "format_instructions": parser.get_format_instructions()
        })
        logger.info(f"ResolutionPlanner: Generated implementation plan with {len(plan.proposed_changes)} change steps.")
        return {"plan": plan, "case_status": "planned"}
    except Exception as e:
        logger.error(f"Planner: Goal-based generation failed: {e}")
        return {"plan": Plan()}


async def resolution_planner_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node (Resolution Planner): Generates a resolution plan based on
    the ticket, hypothesis, and past cases (CBR). Runs post-scoring-gate when
    evidence is sufficient for a confident diagnosis.

    For change tickets with fulfillment goals, generates an implementation plan
    instead of a hypothesis-driven resolution plan.
    """
    ticket = state["ticket"]

    # --- Change ticket path: plan from fulfillment goals ---
    if ticket.mode == "change" and state.get("fulfillment_goals"):
        return await _plan_from_goals(state)

    # --- Incident path: plan from hypothesis ---
    hypotheses = state.get("hypotheses", [])
    sorted_hypotheses = sorted(hypotheses, key=lambda h: h.rank) if hypotheses else []
    active_hypothesis = sorted_hypotheses[0] if sorted_hypotheses else Hypothesis(
        id="default",
        summary="General System Investigation",
        rationale="Initial triage."
    )

    logger.info(f"Planner Agent: Drafting plan for Hypothesis: {active_hypothesis.summary}")

    facts_summary, evidence_summary_text, cbr_context = await _build_common_context(state)

    llm = LLMFactory.get_model_for_agent("planner", temperature=0.0)
    parser = PydanticOutputParser(pydantic_object=Plan)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert Senior IT Support Engineer planning resolution strategies.
Your goal is to create a safe, step-by-step Execution Plan to verify the active hypothesis and resolve the issue.

GUIDELINES:
1. **Safety First**: Do NOT modify system state (restarts, configuration changes, destructive operations) without first verifying the diagnosis.
2. **Diagnosis Steps**: actions to confirm the hypothesis.
3. **Proposed Changes**: actions to fix the root cause (once verified).
4. **Validation**: steps to confirm the fix works.
5. **Rollback**: steps to revert if the fix fails.
6. **Learn from History**: Review the 'Relevant Past Cases' below. If a similar issue was resolved before, prioritize those tools and steps.

Output must be valid JSON adhering to the schema.
"""),
        ("user", """### Context
**Ticket**: {ticket_text}

**Active Hypothesis**: {hypothesis_summary}
{hypothesis_rationale}

### Facts Already Collected
{facts_summary}

### Evidence Already Gathered
{evidence_summary}

{cbr_context}

{format_instructions}
""")
    ])

    chain = prompt | llm | parser

    try:
        plan = await chain.ainvoke({
            "ticket_text": ticket.text,
            "hypothesis_summary": active_hypothesis.summary,
            "hypothesis_rationale": f"Rationale: {active_hypothesis.rationale}" if active_hypothesis.rationale else "",
            "facts_summary": facts_summary,
            "evidence_summary": evidence_summary_text,
            "cbr_context": cbr_context,
            "format_instructions": parser.get_format_instructions()
        })

        logger.info(f"ResolutionPlanner: Generated plan with {len(plan.diagnosis_steps)} diagnosis steps.")
        return {"plan": plan, "case_status": "resolved"}

    except Exception as e:
        logger.error(f"Planner: Generation failed: {e}")
        return {"plan": Plan()}


# Backward-compatible alias
planner_agent_node = resolution_planner_agent_node
