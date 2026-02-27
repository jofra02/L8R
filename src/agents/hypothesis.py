from typing import Any, Dict, List
from src.core.models import GlobalState, Hypothesis
from src.core.llm import LLMFactory
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
import logging
from src.config import settings

logger = logging.getLogger(__name__)

class HypothesisList(BaseModel):
    hypotheses: List[Hypothesis] = Field(description="Ranked list of hypotheses")

async def hypothesis_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Generates and ranks hypotheses.
    """
    facts = state.get("facts", {})
    ticket = state["ticket"]
    
    # If enricher was skipped (no new evidence), avoid redundant re-analysis
    if state.get("meta", {}).get("enricher_skipped"):
        logger.info("Hypothesis Agent: Enricher skipped (no new data). Returning existing hypotheses.")
        # Clear the flag for next iteration
        meta = state.get("meta", {})
        meta["enricher_skipped"] = False
        return {"meta": meta}
    
    logger.info("Hypothesis Agent: Generating hypotheses.")
    
    llm = LLMFactory.get_model_for_agent("hypothesis")
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
    
    system_prompt_text = """You are an elite, top-tier IT Support and Incident Response Engineer (SME Level) operating across multiple disciplines (Networking, Infrastructure, Cloud, Security, Development, Database, Server OS).

        Based on the provided ticket, collected facts, and EXISTING HYPOTHESES, your task is to comprehend the entire scenario, map out all involved components structurally, and generate an updated, strictly-ranked list of logical hypotheses.

        --- DUAL-ROLE ADAPTATION (CRITICAL) ---
        First, determine the INTENT of the ticket:
        1. VALIDATION/INQUIRY (e.g., "validate if X can reach Y", "how is this configured"): Act as an INVESTIGATOR/ANALYST. 
           - DO NOT assume there is a problem/error. 
           - Formulate neutral hypotheses to verify the required state (e.g., "The route to Y exists via interface Z", "Policy ID 12 allows the traffic").
           - Your goal is to gather facts to definitively describe how the environment is configured. Once facts are collected, your final hypotheses should conclude whether the requirement is met and explain WHY, based on the concrete data.
        2. INCIDENT/PROBLEM (e.g., "app is down", "high latency"): Act as a TROUBLESHOOTER.
           - Formulate hypotheses focused on finding the root cause of the broken state (e.g., "A firewall rule is blocking traffic", "BGP peering is down").

        --- ADVANCED TROUBLESHOOTING MINDSET ---
        Adopt the methodical reasoning of a Senior Engineer specific to the implied domain:
        - If NETWORKING (e.g., connectivity, routing, BGP, SD-WAN, firewalling): Methodically reason about the OSI model path. Consider physical interfaces, routing tables, security policies, NAT, IPSec/Overlay tunnels, ARP, or asymmetric routing based on the specific vendor's architecture (e.g., how Vendor X implements a policy-based route vs Vendor Y).
        - If INFRA/SERVER (e.g., Linux, Windows, virtualization): Reason about OS constraints, resource starvation (CPU/Mem/Disk IO), service dependencies, SELinux/AppArmor, DNS resolution, or filesystem unmounts.
        - If APP/DEV (e.g., APIs, Database, Web): Reason about connection pools, deadlock scenarios, certificate expirations, unhandled code exceptions, load balancer SNAT issues, or CORS configuration.
        
        For any vendor explicitly or implicitly mentioned in the scenario, your hypotheses MUST be grounded in that vendor's specific technical architecture, standard behaviors, and known quirks.

        --- METHODOLOGICAL REASONING STEPS ---
        1. Contextualize: What is the symptom? What is the impact? What components are definitely involved?
        2. Deduce: What underlying mechanisms control communication or state between these components?
        3. Formulate: Create concrete, verifiable hypotheses based on the deduction.
        
        --- CRITICAL INSTRUCTIONS ---
        1. Review the 'Current Hypotheses'.
        2. If a hypothesis is 'verifying', cross-reference against collected 'Facts':
           - If facts CONFIRM it definitively, change status to 'verified'.
           - If facts DISPROVE it, change status to 'rejected'.
           - If inconclusive, keep status as 'verifying' (or 'proposed' if you wish to re-prioritize it).
        3. Introduce NEW hypotheses with status 'proposed' when facts suggest a completely new angle or underlying cause.
        4. Rank ALL (active) hypotheses mathematically: Most likely (1) to least likely.
        5. IMPORTANT: Preserve the 'id' of existing hypotheses when updating their status or summary.
        """
        
    if settings.TEST_MODE_FAST:
        system_prompt_text += "\n        6. FAST MODE ENABLED: YOU MUST RETURN EXACTLY 1 (THE MOST LIKELY) HYPOTHESIS. DO NOT RETURN MORE THAN 1."
        
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt_text),
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
