from typing import Any, Dict
from src.core.models import GlobalState, ClientContext
from src.core.context_store import ContextStore
from src.core.database import async_session_factory
import logging

logger = logging.getLogger(__name__)

async def context_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Fetches Client Context.
    Connects to ContextStore.
    """
    customer_id = state.get("customer_id")
    if not customer_id:
        logger.error("No customer_id in state.")
        return {"missing_info": ["customer_id"]}

    logger.info(f"Context Agent: Fetching context for {customer_id}")
    
    async with async_session_factory() as session:
        store = ContextStore(session)
        context = await store.get_active_context(customer_id)
        
        if context:
            logger.info(f"Context found: {context.version}")
            return {"client_context": context}
        else:
            logger.warning("Context not found.")
            # Create empty/default context? Or flag error?
            # For now return None/Default
            default_context = ClientContext(
                customer_id=customer_id, 
                version="v0.0",
                inventory=[],
                baselines=[],
                dependencies=[]
            )
            return {"client_context": default_context, "missing_info": ["client_context_not_found"]}
