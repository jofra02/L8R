from typing import Any, Dict
from src.core.models import GlobalState, HandoffPackage
from src.core.llm import LLMFactory
from langchain_core.messages import SystemMessage, HumanMessage
import logging
import json

logger = logging.getLogger(__name__)

async def response_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Generates a professional IT Support Report.
    """
    ticket = state["ticket"]
    plan = state.get("plan")
    hypotheses = state.get("hypotheses", [])
    evidence = state.get("evidence_refs", [])
    facts = state.get("facts", {})
    
    logger.info("Response Agent: Generating Final Engineering Report.")

    llm = LLMFactory.get_model_for_agent("response") # Use smart model for final synthesis

    # Context Construction
    evidence_summary = "\n".join([f"- [{e.tool_name}]: {e.summary}" for e in evidence])
    hypothesis_summary = "\n".join([f"- {h.summary} (Rank: {h.rank}, Status: {h.status}, Conf: {h.confidence})" for h in hypotheses])

    plan_text = "None"
    if plan:
         steps = "\n".join([f"{i+1}. {s.description} (Expected: {s.expected_outcome})" for i, s in enumerate(plan.diagnosis_steps)])
         plan_text = f"Diagnosis Steps:\n{steps}"

    # Scoring context for pipeline awareness
    scoring = state.get("scoring")
    scoring_text = "No scoring data available."
    if scoring:
        s_conf = scoring.confidence if hasattr(scoring, 'confidence') else scoring.get('confidence', 0)
        s_dec = scoring.decision if hasattr(scoring, 'decision') else scoring.get('decision', '?')
        s_rat = scoring.rationale if hasattr(scoring, 'rationale') else scoring.get('rationale', '')
        s_miss = scoring.missing_facts if hasattr(scoring, 'missing_facts') else scoring.get('missing_facts', [])
        scoring_text = f"Confidence: {s_conf:.0%}, Decision: {s_dec}, Rationale: {s_rat}"
        if s_miss:
            scoring_text += f"\nMissing facts: {', '.join(str(f) for f in s_miss)}"

    # Path analysis + open questions
    from src.utils.state_formatters import format_path_analysis, format_open_questions
    path_text = format_path_analysis(state.get("path_analysis")) or "No path analysis available."
    questions_text = format_open_questions(state.get("open_questions", []))

    # --- Mode-specific guardrail blocks ---
    mode_guardrails = ""
    if ticket.mode == "validation":
        mode_guardrails = """
    MODE-SPECIFIC RULES (validation):
    - PROHIBITED language: "probably", "likely", "possibly", "might", "could be", "appears to", "seems like", "may be missing".
    - Each check item MUST use exactly one of: "Confirmed", "Not confirmed", "Inconclusive".
    - Inconclusive items MUST include the exact next probe (tool name + arguments) needed to resolve.
    - Present checks in table format: | Check | Status | Evidence | Next Probe |
    """
    elif ticket.mode == "inquiry":
        mode_guardrails = """
    MODE-SPECIFIC RULES (inquiry):
    - Answer the question directly and factually.
    - Every statement must cite an evidence snapshot (tool name + summary).
    - Use "Inconclusive" if evidence is insufficient. Do NOT speculate.
    """

    general_guardrails = """
    LANGUAGE GUARDRAILS (all modes):
    - Prefer definitive statements backed by evidence refs over probabilistic hedging.
    - Use "Inconclusive" ONLY when the pipeline has no hypothesis or the scoring confidence is below 50%. When a hypothesis exists with scoring confidence >= 50%, present it as the working diagnosis and note remaining gaps in "Next Steps". Do NOT override the pipeline's diagnosis by independently re-analyzing raw evidence.
    - Every conclusion MUST cite at least one evidence snapshot (tool name + summary).
    - If evidence gaps exist, acknowledge them in "Next Steps" as areas requiring further investigation — do NOT use them to contradict the primary diagnosis.
    - CRITICAL: The Scoring Gate Result, Hypothesis, and Plan represent the pipeline's collective analysis across multiple specialized agents. Your role is to PRESENT these conclusions professionally, not to second-guess them.
    """

    # Retrieve KB references for citation in report
    kb_references = ""
    try:
        from src.core.qdrant import vector_store
        kb_articles = await vector_store.search_knowledge_base(
            query=ticket.text, customer_id=state.get("customer_id", "unknown"), limit=3
        )
        if kb_articles:
            kb_lines = [f"- [{a.get('source', '?')}]: {(a.get('page_content') or a.get('text', ''))[:500]}" for a in kb_articles]
            kb_references = "\n\nReference Documentation:\n" + "\n".join(kb_lines)
    except Exception as e:
        logger.warning(f"Response: KB retrieval failed: {e}")

    system_prompt = f"""
    SYSTEM PROMPT - "IT Support / Incident & Change Engineer"

    Mission: Synthesize the pipeline's diagnostic conclusions into a clear, professional report. You are the FINAL PRESENTER — the hypothesis, scoring, and planning agents have already analyzed the evidence. Your job is to communicate their findings, not to re-evaluate them. Actionable, HIGH-LEVEL conclusion first (TL;DR).

    Contract:
    1) Conclusion: Present the pipeline's diagnosis (from hypothesis + plan). Frame certainty proportional to the Scoring Gate confidence level. For validations/queries: analysis of current state indicating whether it meets requirements. For incidents: Root Cause Diagnosis or Hypothesis.
    2) Evidence: List the key evidence that supports the conclusion.
    3) Gaps / Next Steps: If scoring confidence < 80% or path analysis lists missing evidence, clearly state what remains unverified and what diagnostic actions are needed. This goes in "Next Steps", NOT as a contradiction of the conclusion. Plan / Remediation / Blockers only if applicable.

    Rules:
    - Evidence-only: Do not invent anything or assume something is broken if the ticket only asks for validation.
    - BE CONCISE AND DIRECT. Do not elaborate unless it adds critical value.
    - PRIORITIZE the directly useful conclusion. If the user asked to validate a configuration, and it is correct, conclude "Yes, the configuration is valid and operational".
    - In the "Evidence and Tools Executed" section, group executions and mention failures only if they add context.
    {mode_guardrails}
    {general_guardrails}
    - If Reference Documentation is available, cite relevant KB articles in the report.
    Output Format (Markdown):
    # Technical Report - Ticket {ticket.id}

    ## 1. Conclusion / Primary Diagnosis
    (Short paragraph to the point: Confirmed Root Cause if incident, or Validated State if query/validation).

    ## 2. Brief Context
    (1-2 lines: ticket objective + scope)

    ## 3. Key Evidence and Tools Executed
    (Concise list. Group if the same tool was executed multiple times).

    ## 4. Next Steps (Action / Remediation / Blockers)
    (If there is no problem or the state is correct, state "No action required. Environment operational". If action is needed, indicate what to do or what information is missing).
    """

    user_input = f"""
    Ticket: {ticket.text}
    Ticket Mode: {ticket.mode}
    Context: {state.get('client_context', 'Unknown')}
    
    Facts: {json.dumps(facts, default=str)}
    Evidence Log:
    {evidence_summary}
    
    Hypothesis History:
    {hypothesis_summary}
    
    Current Plan:
    {plan_text}

    Scoring Gate Result:
    {scoring_text}

    Path Analysis:
    {path_text}

    Open Investigation Questions:
    {questions_text}

    {kb_references}

    Task: Generate the Final Report.
    """

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_input)
        ])
        final_report = response.content
    except Exception as e:
        logger.error(f"Response synthesis failed: {e}")
        final_report = "Error generating report. Please check logs."

    # Construct Handoff
    handoff = HandoffPackage(
        case_file_artifacts=[e.storage_ref for e in evidence],
        recommended_escalation={"team": "L2_Ops", "reason": "Automated diagnosis complete. Review report."}
    )
    
    return {
        "final_answer": final_report,
        "handoff": handoff,
        "case_status": "resolved",
    }
