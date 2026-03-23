from typing import Any, Dict
from src.core.models import GlobalState, Classification
from src.core.llm import LLMFactory
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
import logging

logger = logging.getLogger(__name__)

_MODE_OVERRIDE_THRESHOLD = 0.6

async def classifier_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Classifies the ticket.
    Determines technical domains AND ticket mode (incident/change/validation/inquiry).
    """
    ticket = state["ticket"]
    logger.info(f"Classifier Agent: Analyzing ticket {ticket.id} (current mode={ticket.mode})")

    llm = LLMFactory.get_model_for_agent("classifier")
    parser = PydanticOutputParser(pydantic_object=Classification)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert IT Support / Incident Engineer. Perform two classifications:

1. TECHNICAL DOMAINS: Classify into technical domains (e.g., 'network', 'auth', 'database', 'hardware', 'application', 'cloud', 'security', 'storage', 'virtualization', 'identity', 'monitoring', 'devops'). Provide a confidence score (0-1).

2. TICKET MODE: Determine the intent of the ticket. Choose exactly one:
   - "incident": Something is broken, degraded, or not working as expected. Users report failures, errors, outages, performance issues.
   - "change": A request to implement, deploy, modify, provision, upgrade, or migrate something. Includes service requests for new resources.
   - "validation": A request to verify, audit, or confirm that a configuration, setup, policy, or state is correct and compliant.
   - "inquiry": A question seeking information, explanation, or documentation about how something works or is configured.

Set mode_confidence (0-1) for the mode classification."""),
        ("user", "Ticket Text: {text}\nCurrent mode from ticket system: {current_mode}\n\n{format_instructions}")
    ])

    chain = prompt | llm | parser

    try:
        classification = await chain.ainvoke({
            "text": ticket.text,
            "current_mode": ticket.mode,
            "format_instructions": parser.get_format_instructions()
        })

        logger.info(f"Classification result: domains={classification.domains} ({classification.confidence}), "
                     f"mode={classification.mode} ({classification.mode_confidence})")

        # Override ticket mode if classifier is confident enough
        result: Dict[str, Any] = {"classification": classification, "case_status": "triaged"}
        if (classification.mode_confidence >= _MODE_OVERRIDE_THRESHOLD
                and classification.mode != ticket.mode):
            result["ticket"] = ticket.model_copy(update={"mode": classification.mode})
            logger.info(f"Classifier overrode ticket mode: {ticket.mode} -> {classification.mode} "
                        f"(confidence={classification.mode_confidence:.0%})")

        return result

    except Exception as e:
        logger.error(f"Classification failed: {e}")
        return {
            "classification": Classification(
                domains=["unknown"], confidence=0.0, rationale="LLM failure",
                mode=ticket.mode, mode_confidence=0.0,
            ),
            "case_status": "triaged",
        }
