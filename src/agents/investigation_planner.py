"""
Investigation Planner Agent.

Sits after hypothesis generation. Produces structured OpenQuestions
that drive the investigation loop. Each question specifies what to answer,
why it matters, and when it's done — replacing ad-hoc evidence gathering
with targeted, question-driven investigation.
"""
from typing import Any, Dict, List
from src.core.models import GlobalState, OpenQuestion, Hypothesis
from src.core.llm import LLMFactory
from src.utils.state_formatters import (
    format_facts,
    format_hypotheses,
    format_evidence_summaries,
    format_path_analysis,
)
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from langchain_core.output_parsers import PydanticOutputParser
import logging

logger = logging.getLogger(__name__)


class OpenQuestionList(BaseModel):
    questions: List[OpenQuestion] = Field(description="Ordered list of investigation questions")


async def investigation_planner_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Generates structured open questions from hypotheses.
    Consumes hypotheses + existing facts/evidence to identify what must be
    answered next and in what order.
    """
    hypotheses = state.get("hypotheses", [])
    existing_questions = state.get("open_questions", [])
    facts = state.get("facts", {})
    evidence_refs = state.get("evidence_refs", [])
    ticket = state["ticket"]

    # Skip if no hypotheses to plan investigation for
    if not hypotheses:
        logger.info("InvestigationPlanner: No hypotheses to plan for.")
        return {"case_status": "modeled"}

    # Only re-plan if there are unanswered questions from prior iteration
    # or if this is the first planning pass
    open_count = len([q for q in existing_questions if q.status == "open"])
    if existing_questions and open_count > 0:
        logger.info(f"InvestigationPlanner: {open_count} open questions remain. Skipping re-plan.")
        return {"case_status": "planned"}

    logger.info("InvestigationPlanner: Generating investigation questions.")

    llm = LLMFactory.get_model_for_agent("investigation_planner", temperature=0.0)
    parser = PydanticOutputParser(pydantic_object=OpenQuestionList)

    # Build context
    facts_str = format_facts(facts)
    hyp_str = format_hypotheses(hypotheses)
    evidence_str = format_evidence_summaries(evidence_refs, max_items=10)
    path_str = format_path_analysis(state.get("path_analysis"))

    # Identify answered questions for context
    answered_str = "None yet."
    if existing_questions:
        answered = [q for q in existing_questions if q.status == "answered"]
        if answered:
            answered_str = "\n".join(
                [f"- [{q.id}] {q.question} → {q.answer}" for q in answered]
            )

    prompt = f"""You are an Investigation Planner for IT support cases. Your task is to produce
a structured list of questions that must be answered to verify or reject the active hypotheses.

Ticket: {ticket.text}
Ticket Mode: {ticket.mode}

Active Hypotheses:
{hyp_str}

Facts Collected So Far:
{facts_str}

Evidence Gathered:
{evidence_str}

{f"Path Analysis:{chr(10)}{path_str}" if path_str else ""}

Previously Answered Questions:
{answered_str}

INSTRUCTIONS:
1. For each active (proposed/verifying) hypothesis, identify 1-3 specific questions that would confirm or reject it.
2. Questions should be answerable by read-only tool execution (configuration checks, status queries, log inspections).
3. Order questions by diagnostic value — answer the most discriminating questions first.
4. Set `depends_on` if a question requires another to be answered first.
5. Set `done_when` to a concrete, verifiable condition (e.g., "When we have the routing table entry for subnet X").
6. Set `source_hypothesis_id` to link each question to the hypothesis it investigates.
7. Do NOT repeat questions that have already been answered.
8. Generate between 2-6 questions total.

{parser.get_format_instructions()}
"""

    try:
        result = await llm.ainvoke(
            [
                SystemMessage(content="You are a methodical IT investigation planner. Output only valid JSON."),
                HumanMessage(content=prompt),
            ],
        )

        # Parse — handle both raw JSON and wrapped formats
        parsed = parser.parse(result.content)
        new_questions = parsed.questions

        # Merge: keep answered/irrelevant questions, replace open ones with new plan
        preserved = [q for q in existing_questions if q.status in ("answered", "irrelevant")]
        merged = preserved + new_questions

        logger.info(
            f"InvestigationPlanner: Generated {len(new_questions)} questions "
            f"({len(preserved)} previously answered preserved)."
        )

        return {
            "open_questions": merged,
            "case_status": "planned",
        }

    except Exception as e:
        logger.error(f"InvestigationPlanner: Generation failed: {e}")
        return {"case_status": "planned"}
