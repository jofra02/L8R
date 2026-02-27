from typing import Any, Dict, List
from src.core.models import GlobalState, Hypothesis, PathAnalysis, CandidatePath, PathConstraint
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
    
    # Format topology graph for context
    topology_nodes = state.get("topology_nodes", [])
    topology_edges = state.get("topology_edges", [])
    topology_str = "No topology data available yet."
    if topology_edges:
        lines = []
        for e in topology_edges:
            src = e.source_id if hasattr(e, 'source_id') else e.get('source_id', '?')
            tgt = e.target_id if hasattr(e, 'target_id') else e.get('target_id', '?')
            rel = e.relation if hasattr(e, 'relation') else e.get('relation', '?')
            conf = e.confidence if hasattr(e, 'confidence') else e.get('confidence', 0)
            meta = e.metadata if hasattr(e, 'metadata') else e.get('metadata', {})
            meta_str = f" {meta}" if meta else ""
            lines.append(f"- {src} ──[{rel}]──> {tgt} (confidence: {conf:.0%}){meta_str}")
        topology_str = "\n".join(lines)
    
    # Format baselines and known changes
    client_context = state.get("client_context")
    baselines_str = "No baselines defined."
    changes_str = "No recent changes known."
    if client_context:
        ctx = client_context if hasattr(client_context, 'baselines') else type('C', (), client_context)()
        baselines = ctx.baselines if hasattr(ctx, 'baselines') else client_context.get('baselines', [])
        known_changes = ctx.known_changes if hasattr(ctx, 'known_changes') else client_context.get('known_changes', [])
        if baselines:
            bl_lines = []
            for b in baselines:
                comp = b.component_id if hasattr(b, 'component_id') else b.get('component_id', '?')
                metric = b.metric if hasattr(b, 'metric') else b.get('metric', '?')
                val = b.normal_value if hasattr(b, 'normal_value') else b.get('normal_value', '?')
                bl_lines.append(f"- {comp}: {metric} = {val}")
            baselines_str = "\n".join(bl_lines)
        if known_changes:
            kc_lines = []
            for c in known_changes:
                date = c.date if hasattr(c, 'date') else c.get('date', '?')
                desc = c.description if hasattr(c, 'description') else c.get('description', '?')
                kc_lines.append(f"- [{date}] {desc}")
            changes_str = "\n".join(kc_lines)
    
    system_prompt_text = """You are an elite, top-tier IT Support and Incident Response Engineer (SME Level) operating across multiple disciplines (Networking, Infrastructure, Cloud, Security, Development, Database, Server OS).

        Based on the provided ticket, collected facts, and EXISTING HYPOTHESES, your task is to comprehend the entire scenario, map out all involved components structurally, and generate an updated, strictly-ranked list of logical hypotheses.

        --- DUAL-ROLE ADAPTATION (CRITICAL) ---
        First, determine the INTENT of the ticket:
        1. VALIDATION/INQUIRY (e.g., "validate if X can reach Y", "how is this configured"): Act as an INVESTIGATOR/ANALYST. 
           - DO NOT assume there is a problem/error. 
           - Formulate neutral hypotheses to verify the required state (e.g., "The route to Y exists via interface Z", "Policy ID 12 allows the traffic").
           - Your goal is to gather facts to definitively describe how the environment is configured. Once facts are collected, your final hypotheses should conclude whether the requirement is met and explain WHY, based on the concrete data.
        2. INCIDENT/PROBLEM (e.g., "app is down", "high latency"): Act as a TROUBLESHOOTER.
           - Formulate hypotheses focused on finding the root cause of the broken state (e.g., "A policy or rule is blocking the expected traffic", "A critical service dependency is unreachable").

        --- ADVANCED TROUBLESHOOTING MINDSET ---
        Adopt the methodical reasoning of a Senior Engineer specific to the implied domain:
        - Analyze the system layer by layer — from physical/connectivity through logical/application.
        - Consider configuration drift, resource constraints, access control policies, protocol-level issues, and service dependencies.
        - Ground your reasoning in the specific vendor's architecture and known behaviors when the vendor is identifiable.
        - Cross-domain scenarios (e.g., infrastructure + application) should consider interactions between layers.
        
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
        ("user", "Ticket: {text}\n\nFacts:\n{facts}\n\nTopology Graph:\n{topology}\n\nBaselines (normal values):\n{baselines}\n\nRecent Changes:\n{known_changes}\n\nCurrent Hypotheses:\n{hypotheses}\n\n{format_instructions}")
    ])
    
    chain = prompt | llm | parser
    
    try:
        result = await chain.ainvoke({
            "text": state["ticket"].text,
            "facts": facts_str,
            "topology": topology_str,
            "baselines": baselines_str,
            "known_changes": changes_str,
            "hypotheses": hypotheses_str,
            "format_instructions": parser.get_format_instructions()
        })
        
        # Merge/De-dupe logic could go here, but with the explicit prompt we trust the LLM to return the full updated list.
        # We filter out 'rejected' ones from the main reasoning loop eventually, but keeping them for audit is good.
        final_hypotheses = result.hypotheses
        
        logger.info(f"Generated {len(final_hypotheses)} hypotheses.")
        
        # Path analysis: if topology exists, attempt breakpoint reasoning
        result_dict: Dict[str, Any] = {"hypotheses": final_hypotheses}
        
        if topology_edges:
            path_analysis = await _extract_path_analysis(llm, state, topology_str, final_hypotheses)
            if path_analysis:
                result_dict["path_analysis"] = path_analysis
        
        return result_dict
        
    except Exception as e:
        logger.error(f"Hypothesis generation failed: {e}")
        return {"hypotheses": existing_hypotheses}


async def _extract_path_analysis(
    llm, state: GlobalState, topology_str: str, hypotheses: List[Hypothesis]
) -> PathAnalysis | None:
    """Use topology + hypotheses to identify candidate paths, breakpoints, and missing evidence."""
    from langchain_core.messages import SystemMessage, HumanMessage
    import json
    
    ticket_text = state["ticket"].text
    hyp_str = "\n".join([f"- [{h.id}] {h.summary} (status: {h.status})" for h in hypotheses])
    
    prompt = f"""
Given the topology graph and hypotheses below, analyze the flow paths relevant to the ticket.

Ticket: {ticket_text}

Topology Graph:
{topology_str}

Hypotheses:
{hyp_str}

Your task:
1. Identify candidate paths between the source and destination implied by the ticket.
2. For each path, list the hops (edges) and evaluate constraints (does a route exist? does a policy allow? is NAT correct?).
3. Identify the most likely breakpoints — edges where constraints failed or are unknown.
4. Suggest read-only diagnostic probes that would resolve unknown constraints.

Return ONLY a JSON object:
{{
  "candidate_paths": [
    {{
      "path_id": "path_1",
      "source": "source_entity",
      "destination": "dest_entity",
      "hops": ["entity_a->entity_b", "entity_b->entity_c"],
      "constraints": [
        {{"constraint_type": "forward_route", "description": "...", "status": "passed|failed|unknown"}}
      ],
      "confidence": 0.7,
      "status": "viable|blocked|incomplete"
    }}
  ],
  "most_likely_breakpoints": [
    {{"edge": "entity_a->entity_b", "constraint": "policy_match", "reasoning": "..."}}
  ],
  "missing_evidence": ["description of what data is still needed"],
  "suggested_probes": ["read-only diagnostic intent"]
}}

If the ticket does not involve path/flow analysis, return {{"candidate_paths": [], "most_likely_breakpoints": [], "missing_evidence": [], "suggested_probes": []}}.
"""
    
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content="You are an expert at analyzing system topology and identifying flow paths and breakpoints. Output only valid JSON."),
                HumanMessage(content=prompt)
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.content.strip())
        
        # Build PathAnalysis from response
        candidate_paths = []
        for cp in data.get("candidate_paths", []):
            constraints = [
                PathConstraint(
                    constraint_type=c.get("constraint_type", "unknown"),
                    description=c.get("description", ""),
                    status=c.get("status", "unknown"),
                )
                for c in cp.get("constraints", [])
            ]
            candidate_paths.append(CandidatePath(
                path_id=cp.get("path_id", ""),
                source=cp.get("source", ""),
                destination=cp.get("destination", ""),
                hops=cp.get("hops", []),
                constraints=constraints,
                confidence=float(cp.get("confidence", 0)),
                status=cp.get("status", "incomplete"),
            ))
        
        analysis = PathAnalysis(
            candidate_paths=candidate_paths,
            most_likely_breakpoints=data.get("most_likely_breakpoints", []),
            missing_evidence=data.get("missing_evidence", []),
            suggested_probes=data.get("suggested_probes", []),
        )
        
        logger.info(f"Path Analysis: {len(candidate_paths)} paths, {len(analysis.most_likely_breakpoints)} breakpoints")
        return analysis
        
    except Exception as e:
        logger.warning(f"Path analysis extraction failed: {e}")
        return None
