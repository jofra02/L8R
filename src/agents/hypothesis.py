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
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert IT Support AI. Based on the ticket and collected facts, generate potential hypotheses for the root cause (if incident) or implementation path (if change). Identify what evidence is missing."),
        ("user", "Ticket: {text}\n\nFacts:\n{facts}\n\n{format_instructions}")
    ])
    
    chain = prompt | llm | parser
    
    try:
        result = await chain.ainvoke({
            "text": state["ticket"].text,
            "facts": facts_str,
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Generated {len(result.hypotheses)} hypotheses.")
        return {"hypotheses": result.hypotheses}
        
    except Exception as e:
        logger.error(f"Hypothesis generation failed: {e}")
        return {"hypotheses": []}
