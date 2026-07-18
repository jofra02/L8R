"""Versioned assessment scoring.

Only truly evaluated controls (pass / warning / fail) enter the score
denominator; not_applicable, not_evaluated, insufficient_evidence and error
are excluded and surfaced through the coverage figure instead — a score is
never inflated (or deflated) by what could not be evaluated.

    score    = sum(weight * credit) / sum(weight over evaluated) * 100
    coverage = evaluated / (total - not_applicable)
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.assessments.schema import ScoringConfig


def compute_score(results: List[Dict[str, Any]], config: ScoringConfig) -> Dict[str, Any]:
    """Compute overall / per-category / per-target scores.

    ``results`` rows need: status, severity, category, target_id.
    Returns the JSON stored on AssessmentRunORM.score.
    """
    excluded = set(config.excluded_from_denominator)

    def bucket_score(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        weight_total = 0.0
        weight_earned = 0.0
        evaluated = 0
        not_applicable = 0
        for row in rows:
            status = row["status"]
            if status == "not_applicable":
                not_applicable += 1
            if status in excluded:
                continue
            weight = float(config.severity_weights.get(row["severity"], 1.0))
            credit = float(config.status_credit.get(status, 0.0))
            weight_total += weight
            weight_earned += weight * credit
            evaluated += 1

        denominator = len(rows) - not_applicable
        return {
            "score": round(weight_earned / weight_total * 100, 1) if weight_total else None,
            "evaluated": evaluated,
            "total": len(rows),
            "not_applicable": not_applicable,
            "coverage": round(evaluated / denominator, 3) if denominator else None,
        }

    by_category: Dict[str, List[Dict[str, Any]]] = {}
    by_target: Dict[str, List[Dict[str, Any]]] = {}
    for row in results:
        by_category.setdefault(row["category"], []).append(row)
        by_target.setdefault(row["target_id"], []).append(row)

    overall = bucket_score(results)
    return {
        "scoring_version": config.version,
        "overall": overall["score"],
        "coverage": overall["coverage"],
        "evaluated": overall["evaluated"],
        "total": overall["total"],
        "by_category": {cat: bucket_score(rows) for cat, rows in by_category.items()},
        "by_target": {tid: bucket_score(rows) for tid, rows in by_target.items()},
    }


def compute_stats(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Findings distribution stored on AssessmentRunORM.stats."""
    by_status: Dict[str, int] = {}
    findings_by_severity: Dict[str, int] = {}
    for row in results:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        if row["status"] in ("fail", "warning"):
            findings_by_severity[row["severity"]] = findings_by_severity.get(row["severity"], 0) + 1
    return {
        "by_status": by_status,
        "findings_by_severity": findings_by_severity,
        "findings_total": sum(findings_by_severity.values()),
        "critical_findings": findings_by_severity.get("critical", 0),
    }
