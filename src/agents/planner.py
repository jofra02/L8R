from typing import Any, Dict
from src.core.models import GlobalState, Plan, Hypothesis
from src.core.llm import LLMFactory
from src.retrieval.case_retriever import CaseRetriever
from src.core.qdrant import vector_store
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
import logging

logger = logging.getLogger(__name__)

async def planner_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Generates a plan based on the ticket, hypothesis, and past cases (CBR).
    """
    ticket = state["ticket"]
    hypotheses = state.get("hypotheses", [])
    
    # Select the most relevant hypothesis (sorted by rank)
    sorted_hypotheses = sorted(hypotheses, key=lambda h: h.rank) if hypotheses else []
    active_hypothesis = sorted_hypotheses[0] if sorted_hypotheses else Hypothesis(
        id="default", 
        summary="General System Investigation", 
        rationale="Initial triage."
    )
    
    logger.info(f"Planner Agent: Drafting plan for Hypothesis: {active_hypothesis.summary}")
    
    # --- 1. Case-Based Reasoning (RAG) ---
    cbr_context = ""
    try:
        retriever = CaseRetriever(vector_store)
        similar_cases = await retriever.retrieve_similar_cases(
            ticket, customer_id=state.get("customer_id", "unknown"), limit=3
        )
        cbr_context = retriever.format_cases_for_context(similar_cases)
    except Exception as e:
        logger.warning(f"Planner: CBR retrieval failed (proceeding without past cases): {e}")
        cbr_context = "No similar past cases available."

    # --- 2. Setup LLM & Parser ---
    llm = LLMFactory.get_model_for_agent("planner", temperature=0.0) # Precise planning
    parser = PydanticOutputParser(pydantic_object=Plan)
    
    # --- 3. Formulate Prompt ---
    # We inject the CBR context to guide the LLM
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert Senior IT Support Engineer planning resolution strategies.
Your goal is to create a safe, step-by-step Execution Plan to verify the active hypothesis and resolve the issue.

GUIDELINES:
1. **Safety First**: Do NOT modify system state (reboots, config changes) without first verifying the diagnosis.
2. **Diagnosis Steps**: actions to confirm the hypothesis.
3. **Proposed Changes**: actions to fix the root cause (once verified).
4. **Validation**: steps to confirm the fix works.
5. **Rollback**: steps to revert if the fix fails.
6. **Learn from History**: Review the 'Relevant Past Cases' below. If a similar issue was resolved before, prioritize those tools and steps.

Output must be valid JSON adhering to the schema.
"""),
        ("user", """### Context
**Ticket**: {ticket_text}

**Active Hypothesis**: {hypothesis_summary}
{hypothesis_rationale}

### Facts Already Collected
{facts_summary}

### Evidence Already Gathered
{evidence_summary}

{cbr_context}

{format_instructions}
""")
    ])
    
    chain = prompt | llm | parser
    
    # --- Build facts and evidence summaries ---
    facts = state.get("facts", {})
    evidence_refs = state.get("evidence_refs", [])
    facts_summary = "\n".join([f"- {k}: {v}" for k, v in facts.items() if not k.startswith("_")]) or "No facts collected yet."
    evidence_summary_text = "\n".join([f"- [{e.tool_name}]: {e.summary}" for e in evidence_refs[-10:]]) or "No evidence gathered yet."

    try:
        plan = await chain.ainvoke({
            "ticket_text": ticket.text,
            "hypothesis_summary": active_hypothesis.summary,
            "hypothesis_rationale": f"Rationale: {active_hypothesis.rationale}" if active_hypothesis.rationale else "",
            "facts_summary": facts_summary,
            "evidence_summary": evidence_summary_text,
            "cbr_context": cbr_context,
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Planner: Generated plan with {len(plan.diagnosis_steps)} diagnosis steps.")
        return {"plan": plan}
        
    except Exception as e:
        logger.error(f"Planner: Generation failed: {e}")
        # Return empty plan implies "Human Intervention Required" usually
        return {"plan": Plan()}
