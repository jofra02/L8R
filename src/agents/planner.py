from typing import Any, Dict
from src.core.models import GlobalState, Plan, PlanStep
from src.core.llm import LLMFactory
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
import logging

logger = logging.getLogger(__name__)

async def planner_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Generates a plan.
    """
    ticket = state["ticket"]
    hypotheses = state.get("hypotheses", [])
    
    logger.info("Planner Agent: Drafting plan.")
    
    # Select leading hypothesis (Prioritize Verified -> Proposed -> ignore Rejected)
    sorted_hypotheses = sorted(hypotheses, key=lambda x: x.rank)
    target_hypothesis = next((h for h in sorted_hypotheses if h.status == "verified"), None)
    
    if not target_hypothesis:
        # Fallback to top proposed if none verified (and not rejected)
        target_hypothesis = next((h for h in sorted_hypotheses if h.status == "proposed"), None)
        
    hypothesis_text = target_hypothesis.summary if target_hypothesis else "Analyze root cause (No verified hypothesis)"
    
    llm = LLMFactory.get_main_llm()
    parser = PydanticOutputParser(pydantic_object=Plan)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert IT Support / Incident Engineer. Create a safe, step-by-step plan to verify the hypothesis and resolve the issue. Do NOT include steps that modify the system state without approval. Focus on diagnosis and verification first."),
        ("user", "Ticket: {text}\n\nHypothesis: {hypothesis}\n\n{format_instructions}")
    ])
    
    chain = prompt | llm | parser
    
    try:
        plan = await chain.ainvoke({
            "text": ticket.text,
            "hypothesis": hypothesis_text,
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Plan generated with {len(plan.diagnosis_steps)} diagnosis steps.")
        return {"plan": plan}
        
    except Exception as e:
        logger.error(f"Planning failed: {e}")
        # Return empty plan
        return {"plan": Plan()}
