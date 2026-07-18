"""Evaluation engine: applies a definition's controls to collected evidence.

Priority per the spec: deterministic rules/parsers first; LLM only for
``llm``/``hybrid`` evaluation types. Missing required evidence is always
``insufficient_evidence`` — never ``fail``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.assessments.evaluation.rules import (
    EvalOutcome,
    get_parser,
    get_rule,
)
from src.assessments.schema import ControlDef

logger = logging.getLogger(__name__)

# Severity order used to combine hybrid verdicts (worse wins, conservative)
_STATUS_RANK = {"pass": 0, "warning": 1, "fail": 2}


@dataclass
class ControlEvaluation:
    outcome: EvalOutcome
    method: str  # rule|parser|llm|hybrid
    llm_output: Optional[Dict[str, Any]] = None


def _run_deterministic(kind: str, name: str, evidence: Dict[str, Any],
                       params: Dict[str, Any]) -> EvalOutcome:
    try:
        evaluator = get_rule(name) if kind == "rule" else get_parser(name)
    except KeyError as e:
        # Definitions are validated at sync time; reaching this means drift.
        return EvalOutcome(status="error", explanation=str(e), confidence=0.0)
    try:
        return evaluator(evidence, params)
    except Exception as e:  # noqa: BLE001 — evaluator bug must not kill the run
        logger.exception(f"Deterministic evaluator '{name}' raised")
        return EvalOutcome(status="error", explanation=f"Evaluator error: {e}", confidence=0.0)


def _combine_hybrid(rule: EvalOutcome, llm: EvalOutcome) -> EvalOutcome:
    """Conservative merge of the deterministic and LLM verdicts."""
    if llm.status == "error":
        return EvalOutcome(
            status=rule.status,
            explanation=rule.explanation + " [LLM enrichment unavailable]",
            recommendation=rule.recommendation,
            evidence_refs=rule.evidence_refs,
            confidence=min(rule.confidence, 0.8),
        )
    if rule.status == "insufficient_evidence":
        return llm
    if llm.status == "insufficient_evidence":
        return EvalOutcome(
            status=rule.status,
            explanation=rule.explanation + f" [LLM: {llm.explanation}]",
            recommendation=rule.recommendation,
            evidence_refs=rule.evidence_refs,
            confidence=min(rule.confidence, llm.confidence if llm.confidence else 0.8),
        )

    worse, better = (rule, llm) if _STATUS_RANK.get(rule.status, 0) >= _STATUS_RANK.get(llm.status, 0) else (llm, rule)
    refs = list(dict.fromkeys([*rule.evidence_refs, *llm.evidence_refs]))
    return EvalOutcome(
        status=worse.status,
        explanation=f"{rule.explanation} [LLM assessment: {llm.explanation}]",
        recommendation=llm.recommendation or rule.recommendation,
        evidence_refs=refs,
        confidence=min(rule.confidence, llm.confidence),
    )


async def evaluate_control(
    control: ControlDef,
    evidence: Dict[str, Any],
    device_context: str = "",
    llm_enabled: bool = True,
) -> ControlEvaluation:
    """Evaluate one control against the normalized evidence of one target.

    ``evidence`` maps step_id -> normalized payload for successfully collected
    steps only; missing keys mean the step failed or was skipped.
    """
    missing = [ev for ev in control.required_evidence if ev not in evidence]
    if missing:
        return ControlEvaluation(
            outcome=EvalOutcome(
                status="insufficient_evidence",
                explanation=f"Required evidence not collected: {', '.join(missing)}.",
                evidence_refs=[ev for ev in control.required_evidence if ev in evidence],
                confidence=1.0,
            ),
            method=control.evaluation.type,
        )

    ev_type = control.evaluation.type

    if ev_type == "rule":
        return ControlEvaluation(
            outcome=_run_deterministic("rule", control.evaluation.rule, evidence, control.params),
            method="rule",
        )

    if ev_type == "parser":
        return ControlEvaluation(
            outcome=_run_deterministic("parser", control.evaluation.parser, evidence, control.params),
            method="parser",
        )

    # LLM-involving paths — import lazily so deterministic-only runs never
    # touch LLM dependencies.
    from src.assessments.evaluation.llm_evaluator import evaluate_with_llm

    if ev_type == "llm":
        if not llm_enabled:
            return ControlEvaluation(
                outcome=EvalOutcome(
                    status="not_evaluated",
                    explanation="LLM evaluation disabled for this run.",
                    confidence=1.0,
                ),
                method="llm",
            )
        outcome = await evaluate_with_llm(control, evidence, device_context)
        return ControlEvaluation(outcome=outcome, method="llm")

    # hybrid
    rule_outcome = _run_deterministic("rule", control.evaluation.rule, evidence, control.params)
    if not llm_enabled:
        return ControlEvaluation(outcome=rule_outcome, method="rule")

    llm_outcome = await evaluate_with_llm(
        control, evidence, device_context, rule_outcome=rule_outcome
    )
    combined = _combine_hybrid(rule_outcome, llm_outcome)
    return ControlEvaluation(
        outcome=combined,
        method="hybrid" if llm_outcome.status != "error" else "rule",
        llm_output={
            "status": llm_outcome.status,
            "explanation": llm_outcome.explanation,
            "confidence": llm_outcome.confidence,
        },
    )
