"""
Goal Decomposer Agent.

Handles change/request tickets by decomposing the requested action into
structured fulfillment goals with preconditions, validation criteria,
and sub-goal dependencies. This replaces hypothesis-driven investigation
for tickets that are not troubleshooting problems but fulfilling requests.
"""
from typing import Any, Dict, List
from src.core.models import GlobalState, FulfillmentGoal
from src.core.llm import LLMFactory
from src.utils.state_formatters import format_facts, format_evidence_summaries
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from langchain_core.output_parsers import PydanticOutputParser
import logging

logger = logging.getLogger(__name__)


class FulfillmentGoalList(BaseModel):
    goals: List[FulfillmentGoal] = Field(description="Ordered list of fulfillment goals")


async def goal_decomposer_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Decomposes change/request tickets into structured goals.
    Runs instead of hypothesis generation for non-troubleshooting tickets.
    """
    ticket = state["ticket"]
    components = state.get("components", [])
    facts = state.get("facts", {})
    evidence_refs = state.get("evidence_refs", [])
    existing_goals = state.get("fulfillment_goals", [])

    # Skip if goals already decomposed and in progress
    pending = [g for g in existing_goals if g.status in ("pending", "in_progress")]
    if pending:
        logger.info(f"GoalDecomposer: {len(pending)} goals still active. Skipping re-decomposition.")
        return {"case_status": "modeled"}

    logger.info("GoalDecomposer: Decomposing fulfillment goals.")

    llm = LLMFactory.get_model_for_agent("goal_decomposer", temperature=0.0)
    parser = PydanticOutputParser(pydantic_object=FulfillmentGoalList)

    facts_str = format_facts(facts)
    evidence_str = format_evidence_summaries(evidence_refs, max_items=8)
    components_str = "\n".join(
        [f"- {c.id} ({c.role}, vendor: {c.vendor or 'unknown'})" for c in components]
    ) or "No components identified."

    prompt = f"""You are an IT Change/Request Fulfillment Planner.

Ticket: {ticket.text}
Ticket Mode: {ticket.mode}

Components Involved:
{components_str}

Facts Collected:
{facts_str}

Evidence:
{evidence_str}

INSTRUCTIONS:
1. Decompose the requested change/action into discrete, verifiable goals.
2. Each goal must have:
   - A clear description of what needs to be accomplished
   - Preconditions that must hold before attempting this goal
   - Validation criteria to confirm the goal is met
3. Order goals by dependency — prerequisite goals first.
4. Use `sub_goals` to reference child goal IDs when a goal breaks into smaller steps.
5. Generate between 1-5 goals.
6. All goals start with status "pending".

{parser.get_format_instructions()}
"""

    try:
        result = await llm.ainvoke(
            [
                SystemMessage(content="You are an IT change management specialist. Output only valid JSON."),
                HumanMessage(content=prompt),
            ],
        )

        parsed = parser.parse(result.content)
        goals = parsed.goals

        # Preserve completed goals from prior runs
        completed = [g for g in existing_goals if g.status == "completed"]
        merged = completed + goals

        logger.info(f"GoalDecomposer: Decomposed into {len(goals)} goals.")

        return {
            "fulfillment_goals": merged,
            "case_status": "modeled",
        }

    except Exception as e:
        logger.error(f"GoalDecomposer: Decomposition failed: {e}")
        return {"case_status": "modeled"}
