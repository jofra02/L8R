from typing import Any, Dict
from src.core.models import GlobalState, Classification
from src.core.llm import LLMFactory
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
import logging

logger = logging.getLogger(__name__)

async def classifier_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Classifies the ticket.
    Determines domains and severity validation.
    """
    ticket = state["ticket"]
    logger.info(f"Classifier Agent: Analyzing ticket {ticket.id}")
    
    llm = LLMFactory.get_model_for_agent("classifier")
    parser = PydanticOutputParser(pydantic_object=Classification)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert IT Support / Incident Engineer. Classify the following ticket into technical domains (e.g., 'network', 'auth', 'database', 'hardware', 'application', 'cloud', 'security', 'storage', 'virtualization', 'identity', 'monitoring', 'devops'). Provide a confidence score (0-1)."),
        ("user", "Ticket Text: {text}\n\n{format_instructions}")
    ])
    
    chain = prompt | llm | parser
    
    try:
        classification = await chain.ainvoke({
            "text": ticket.text,
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Classification result: {classification.domains} ({classification.confidence})")
        return {"classification": classification}
        
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        # Fallback
        return {
            "classification": Classification(domains=["unknown"], confidence=0.0, rationale="LLM failure")
        }
