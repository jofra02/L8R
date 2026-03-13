from typing import Any, Dict
from src.core.models import GlobalState, HandoffPackage
from src.core.llm import LLMFactory
from langchain_core.messages import SystemMessage, HumanMessage
from datetime import datetime
import uuid
import logging
import json
import os

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

    # 0. Check for Human-in-the-Loop Blocking Requirements
    pending_reqs = state.get("pending_requirements", [])
    if pending_reqs:
        logger.warning(f"Response Agent: Pausing for user input. {len(pending_reqs)} requirements.")
        
        # Dump to data/needs.json
        os.makedirs("data", exist_ok=True)
        needs_file = os.path.join("data", "needs.json")
        state_file = os.path.join("data", "paused_state.json")
        
        # User-friendly format
        simple_items = []
        for req in pending_reqs:
            simple_items.append({
                "key": req.key,
                "tool": req.tool_name,
                "component": req.component_id,
                "instruction": f"I need {req.description} to execute '{req.tool_name}' on {req.component_id}.",
                "value": None # USER INPUT HERE
            })

        needs_data = {
            "ticket_id": ticket.id,
            "status": "paused_for_input",
            "required_inputs": simple_items
        }
        
        with open(needs_file, "w") as f:
            json.dump(needs_data, f, indent=2)

        # Initialize msg early
        msg = f"""
# 🛑 Action Required: Missing Information

The agent has paused execution because it lacks critical information to proceed.

## Instructions
1. Open `{needs_file}`.
2. Locate the `"value": null` fields.
3. Replace `null` with the correct information (e.g. `"10.1.1.1"`).
4. Save the file.
5. Resume execution:
   ```bash
   uv run python -m src.main resume --file {needs_file} --state {state_file}
   ```

## Pending Requirements
"""
        for req in pending_reqs:
            msg += f"- {req.description} (for {req.tool_name})\n"
            
        # Dump Full State for Resume (Simulated Checkpoint)
        try:
             class StateEncoder(json.JSONEncoder):
                 def default(self, obj):
                     if isinstance(obj, (datetime, uuid.UUID)):
                         return str(obj)
                     if hasattr(obj, "model_dump"):
                         return obj.model_dump(mode='json') # Pydantic V2
                     return super().default(obj)
             
             state_json = json.dumps(state, cls=StateEncoder, indent=2)
             
             with open(state_file, "w") as f:
                 f.write(state_json)
                 
        except Exception as e:
             logger.error(f"Failed to save state checkpoint: {e}")
             msg += "\n\n**WARNING: State checkpoint failed to save. Resume might not be possible.**"
            
        return {
            "final_answer": msg,
            "handoff": HandoffPackage(case_file_artifacts=[needs_file])
        }

    llm = LLMFactory.get_model_for_agent("response") # Use smart model for final synthesis
    
    # Context Construction
    evidence_summary = "\n".join([f"- [{e.tool_name}]: {e.summary}" for e in evidence])
    hypothesis_summary = "\n".join([f"- {h.summary} (Rank: {h.rank}, Status: {h.status}, Conf: {h.confidence})" for h in hypotheses])
    
    plan_text = "None"
    if plan:
         steps = "\n".join([f"{i+1}. {s.description} (Expected: {s.expected_outcome})" for i, s in enumerate(plan.diagnosis_steps)])
         plan_text = f"Diagnosis Steps:\n{steps}"

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
    - Use "Inconclusive" instead of "probably", "likely", "might", "could be", "appears to", "seems like".
    - Every conclusion MUST cite at least one evidence snapshot (tool name + summary).
    - If evidence is insufficient for a definitive conclusion, state "Inconclusive" and specify the exact diagnostic action needed to resolve.
    """

    system_prompt = f"""
    SYSTEM PROMPT - "IT Support / Incident & Change Engineer"

    Mission: Resolve problems, validate configurations, and assess IT system states objectively and verifiably. Actionable, HIGH-LEVEL conclusion first (TL;DR).

    Contract:
    1) Conclusion (For validations/queries: analysis of current state indicating whether it meets requirements. For incidents: Root Cause Diagnosis or Hypothesis).
    2) Evidence (Supporting data for the conclusion, listing what was checked).
    3) Plan / Remediation / Blockers (Only if applicable or there is a problem to fix).

    Rules:
    - Evidence-only: Do not invent anything or assume something is broken if the ticket only asks for validation.
    - BE CONCISE AND DIRECT. Do not elaborate unless it adds critical value.
    - PRIORITIZE the directly useful conclusion. If the user asked to validate a configuration, and it is correct, conclude "Yes, the configuration is valid and operational".
    - In the "Evidence and Tools Executed" section, group executions and mention failures only if they add context.
    {mode_guardrails}
    {general_guardrails}
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
        "handoff": handoff
    }
