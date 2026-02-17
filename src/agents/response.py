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
    
    llm = LLMFactory.get_llm_model("smart") # Use smart model for final synthesis
    
    # Context Construction
    evidence_summary = "\n".join([f"- [{e.tool_name}]: {e.summary}" for e in evidence])
    hypothesis_summary = "\n".join([f"- {h.summary} (Rank: {h.rank}, Status: {h.status}, Conf: {h.confidence})" for h in hypotheses])
    
    plan_text = "None"
    if plan:
         steps = "\n".join([f"{i+1}. {s.description} (Expected: {s.expected_outcome})" for i, s in enumerate(plan.diagnosis_steps)])
         plan_text = f"Diagnosis Steps:\n{steps}"

    system_prompt = """
    SYSTEM PROMPT — “IT Support / Incident & Change Engineer”

    Misión: Resolver problemas y ejecutar cambios de forma segura y verificable. Output accionable.

    Contrato:
    1) Diagnóstico (Hipótesis verificada o Top 3 probables).
    2) Plan de pruebas (High-signal).
    3) Plan de remediación (Pasos exactos, rollback).
    4) Missing Info (Minimum sufficient context).

    Reglas:
    - Evidence-only: No inventes nada. "Supuesto: ..." si es necesario.
    - Read-only first.
    - Version-aware.
    - No filler. Español directo. Términos IT en inglés.

    Formato de Salida (Markdown):
    # Reporte Técnico - Ticket {ticket_id}

    ## 1. Contexto
    (1-2 líneas: síntoma + alcance)

    ## 2. Hallazgos & Evidencia
    (Bullets con hechos confirmados)

    ## 3. Diagnóstico
    (Causa Raíz confirmada o Hipótesis Principal)

    ## 4. Plan de Acción / Troubleshooting
    (Pasos numerados para verificar o resolver)

    ## 5. Remediación (Si aplica)
    (Pasos de cambio + Rollback)

    ## 6. Información Faltante (Si aplica)
    (Qué se necesita para cerrar el caso)
    """

    user_input = f"""
    Ticket: {ticket.text}
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
