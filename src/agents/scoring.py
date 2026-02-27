"""
Scoring / Decision Engine Agent.

Runs after hypothesis verification (enricher → hypothesis → scoring → supervisor).
Computes risk score, confidence, and gates the decision:
  - proceed_to_plan: enough evidence, confident hypothesis → go to planner
  - needs_more_evidence: hypothesis active but not enough facts → investigator
  - escalate_to_human: high risk + low confidence → response with HITL
"""
from typing import Any, Dict
from src.core.models import GlobalState, ScoringResult, Hypothesis
from src.core.llm import LLMFactory
from src.config import settings
import logging

logger = logging.getLogger(__name__)

# Confidence thresholds
CONFIDENCE_PROCEED = 0.7    # Above this → proceed to plan
CONFIDENCE_ESCALATE = 0.3   # Below this + high severity → escalate

# Severity multipliers for risk score
SEVERITY_WEIGHTS = {
    "critical": 4.0,
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
}


async def scoring_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    Deterministic + heuristic scoring engine.
    No LLM call — pure state analysis for speed and reliability.
    """
    hypotheses = state.get("hypotheses", [])
    facts = state.get("facts", {})
    evidence_refs = state.get("evidence_refs", [])
    ticket = state["ticket"]
    pending_reqs = state.get("pending_requirements", [])
    
    logger.info("Scoring Agent: Evaluating state for decision gate.")
    
    # 1. Find the best hypothesis
    active_hypotheses = [h for h in hypotheses if h.status in ("proposed", "verifying", "verified")]
    if active_hypotheses:
        sorted_hyp = sorted(active_hypotheses, key=lambda h: h.rank)
        best = sorted_hyp[0]
    else:
        best = None
    
    # 2. Compute evidence coverage
    # How many required facts does the best hypothesis have covered?
    if best and best.required_facts:
        covered = len(best.supporting_facts)
        required = len(best.required_facts)
        evidence_coverage = min(covered / max(required, 1), 1.0)
    else:
        # No required_facts declared → use evidence count heuristic
        evidence_coverage = min(len(evidence_refs) / 3.0, 1.0)  # 3+ evidence items → full coverage
    
    # 3. Compute confidence
    # Weighted average of:
    #   - Hypothesis confidence (from LLM)
    #   - Evidence coverage (from fact counting)
    #   - Fact density (non-internal facts / expected)
    hyp_confidence = best.confidence if best else 0.0
    real_facts = {k: v for k, v in facts.items() if not k.startswith("_")}
    fact_density = min(len(real_facts) / 5.0, 1.0)  # 5+ facts → full density
    
    confidence = (
        hyp_confidence * 0.5 +
        evidence_coverage * 0.3 +
        fact_density * 0.2
    )
    
    # 4. Compute risk score (1-10)
    severity_weight = SEVERITY_WEIGHTS.get(ticket.severity, 2.0)
    # High severity + low confidence = high risk
    risk_score = min(severity_weight * (2.0 - confidence) * 2.5, 10.0)
    risk_score = round(max(risk_score, 1.0), 1)
    
    # 5. Decision gate
    if pending_reqs:
        decision = "escalate_to_human"
        rationale = f"Blocked by {len(pending_reqs)} pending requirements from user."
        missing_facts = [r.description for r in pending_reqs]
    elif best and best.status == "verified" and confidence >= CONFIDENCE_PROCEED:
        decision = "proceed_to_plan"
        rationale = f"Hypothesis '{best.summary[:60]}' verified with {confidence:.0%} confidence."
        missing_facts = []
    elif confidence >= CONFIDENCE_PROCEED and len(evidence_refs) >= 2:
        decision = "proceed_to_plan"
        rationale = f"Sufficient evidence ({len(evidence_refs)} items) with {confidence:.0%} confidence."
        missing_facts = []
    elif confidence < CONFIDENCE_ESCALATE and ticket.severity in ("critical", "high"):
        decision = "escalate_to_human"
        rationale = f"Low confidence ({confidence:.0%}) on {ticket.severity} severity. Human review needed."
        missing_facts = best.required_facts if best else ["Initial investigation required"]
    else:
        decision = "needs_more_evidence"
        rationale = f"Confidence {confidence:.0%} below threshold ({CONFIDENCE_PROCEED:.0%}). More investigation needed."
        missing_facts = []
        if best:
            # Find uncovered required facts
            covered_set = set(best.supporting_facts)
            missing_facts = [f for f in best.required_facts if f not in covered_set]
    
    scoring = ScoringResult(
        risk_score=risk_score,
        confidence=round(confidence, 3),
        evidence_coverage=round(evidence_coverage, 3),
        decision=decision,
        rationale=rationale,
        missing_facts=missing_facts,
    )
    
    logger.info(
        f"Scoring Agent: risk={scoring.risk_score}, confidence={scoring.confidence:.0%}, "
        f"decision={scoring.decision} — {scoring.rationale}"
    )
    
    return {"scoring": scoring}
