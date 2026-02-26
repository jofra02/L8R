from typing import Any, Dict, List
from src.core.models import GlobalState, Component
from src.core.llm import LLMFactory
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)

class ComponentList(BaseModel):
    components: List[Component] = Field(description="List of potential components involved")

async def mapper_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Maps ticket text to components.
    identifies devices, IP addresses, services, etc.
    """
    ticket = state["ticket"]
    context = state.get("client_context")
    logger.info(f"Mapper Agent: Scoping ticket {ticket.id}")
    
    llm = LLMFactory.get_model_for_agent("mapper")
    parser = PydanticOutputParser(pydantic_object=ComponentList)
    
    # Context summary for the LLM
    inventory_summary = "No inventory available."
    if context and context.inventory:
        # If inventory is small, we pass it all.
        if len(context.inventory) <= 50:
             items_str = "\n".join([f"- {c.id}: {c.ref} ({c.vendor} {c.role})" for c in context.inventory])
             inventory_summary = f"Customer has {len(context.inventory)} assets:\n{items_str}"
        else:
             inventory_summary = f"Customer has {len(context.inventory)} assets in inventory."
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert IT Support / Incident Engineer. Analyze the ticket and identify technical components (devices, IPs, URLs, services, users). Match against inventory if possible. Infer the 'vendor' (e.g. Fortinet, Cisco, AWS, Microsoft) if explicitly mentioned or implied by the context."),
        ("user", "Context: {inventory}\n\nTicket: {text}\n\n{format_instructions}")
    ])
    
    chain = prompt | llm | parser
    
    try:
        result = await chain.ainvoke({
            "inventory": inventory_summary,
            "text": ticket.text,
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Mapper result: Found {len(result.components)} components.")
        return {"components": result.components}
        
    except Exception as e:
        logger.error(f"Mapper failed: {e}")
        return {"components": [], "missing_info": ["mapper_error"]}
