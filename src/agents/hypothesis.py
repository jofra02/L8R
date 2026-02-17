from typing import Any, Dict, List
from src.core.models import GlobalState, Hypothesis
from src.core.llm import LLMFactory
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)

class HypothesisList(BaseModel):
    hypotheses: List[Hypothesis] = Field(description="Ranked list of hypotheses")

async def hypothesis_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Generates and ranks hypotheses.
    """
    facts = state.get("facts", {})
    ticket = state["ticket"]
    
    logger.info("Hypothesis Agent: Generating hypotheses.")
    
    llm = LLMFactory.get_main_llm()
    parser = PydanticOutputParser(pydantic_object=HypothesisList)
    
    # Format facts for prompt
    facts_str = "\n".join([f"- {k}: {v}" for k, v in facts.items()]) or "No specific facts collected yet."
    
    # Format existing hypotheses for context
    existing_hypotheses = state.get("hypotheses", [])
    hypotheses_str = "No existing hypotheses."
    if existing_hypotheses:
        hypotheses_str = "\n".join([
            f"- [{h.id}] ({h.status}) {h.summary} (Rank: {h.rank})" 
            for h in existing_hypotheses
        ])
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert IT Support / Incident Engineer. 
        Based on the ticket, collected facts, and EXISTING HYPOTHESES, generate an updated ranked list of hypotheses.
        
        CRITICAL INSTRUCTIONS:
        1. Review the 'Current Hypotheses'.
        2. If a hypothesis is 'verifying', check the 'Facts'. 
           - If facts CONFIRM it, change status to 'verified'.
           - If facts DISPROVE it, change status to 'rejected'.
           - If inconclusive, keep status as 'verifying' (or 'proposed' if you want to re-rank it).
        3. Introduce NEW hypotheses with status 'proposed' if the facts suggest a new angle.
        4. Rank ALL (active) hypotheses from most likely (1) to least likely.
        5. IMPORTANT: Preserve the 'id' of existing hypotheses if you are updating them.
        """),
        ("user", "Ticket: {text}\n\nFacts:\n{facts}\n\nCurrent Hypotheses:\n{hypotheses}\n\n{format_instructions}")
    ])
    
    chain = prompt | llm | parser
    
    try:
        result = await chain.ainvoke({
            "text": state["ticket"].text,
            "facts": facts_str,
            "hypotheses": hypotheses_str,
            "format_instructions": parser.get_format_instructions()
        })
        
        # Merge/De-dupe logic could go here, but with the explicit prompt we trust the LLM to return the full updated list.
        # We filter out 'rejected' ones from the main reasoning loop eventually, but keeping them for audit is good.
        final_hypotheses = result.hypotheses
        
        logger.info(f"Generated {len(final_hypotheses)} hypotheses.")
        return {"hypotheses": final_hypotheses}
        
    except Exception as e:
        logger.error(f"Hypothesis generation failed: {e}")
        # Fallback: return existing to avoid losing state on error
        return {"hypotheses": existing_hypotheses}
