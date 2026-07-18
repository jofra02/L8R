"""Report model builder — view-independent, export-ready.

Builds the JSON report model persisted in ``assessment_reports.model``.
Rendering (HTML view today, PDF/DOCX later) consumes this model; the builder
never emits presentation markup beyond plain markdown strings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

FORMAT_VERSION = "1.0"

_SEVERITY_ORDER = ["critical", "high", "medium", "low"]


def build_report_model(
    run: Any,                      # AssessmentRunORM
    targets: List[Any],            # AssessmentTargetORM
    executions: List[Any],         # AssessmentCollectionExecutionORM
    results: List[Any],            # AssessmentControlResultORM
    definition_content: Dict[str, Any],
) -> Dict[str, Any]:
    meta = definition_content.get("assessment", {})
    target_names = {t.id: t.device_name for t in targets}

    findings = [
        {
            "control_id": r.control_id,
            "title": r.title,
            "category": r.category,
            "severity": r.severity,
            "status": r.status,
            "device": target_names.get(r.target_id, r.target_id),
            "explanation": r.explanation,
            "recommendation": r.recommendation,
            "references": r.references or [],
            "method": r.method,
            "confidence": r.confidence,
            "evidence_refs": r.evidence_refs or [],
        }
        for r in sorted(
            results,
            key=lambda r: (_SEVERITY_ORDER.index(r.severity)
                           if r.severity in _SEVERITY_ORDER else 99),
        )
        if r.status in ("fail", "warning")
    ]

    coverage_rows = [
        {
            "device": target_names.get(e.target_id, e.target_id),
            "step_id": e.step_id,
            "tool": e.tool_name,
            "status": e.status,
            "error_type": e.error_type,
            "duration_ms": e.duration_ms,
            "truncated": bool(e.truncated),
        }
        for e in executions
    ]

    failed_steps = [c for c in coverage_rows if c["status"] in ("failed", "timeout")]
    not_evaluated = [
        r.control_id for r in results
        if r.status in ("not_evaluated", "insufficient_evidence", "error")
    ]

    limitations: List[str] = []
    if failed_steps:
        limitations.append(
            f"{len(failed_steps)} collection step(s) failed; the affected controls "
            f"were reported as insufficient_evidence, not as failures."
        )
    if not_evaluated:
        limitations.append(
            f"Controls without a verdict (excluded from the score): "
            f"{', '.join(sorted(set(not_evaluated)))}."
        )
    score = run.score or {}
    if score.get("coverage") is not None and score["coverage"] < 1.0:
        limitations.append(
            f"Score coverage is {score['coverage']:.0%} — the score reflects only "
            f"the controls that could be evaluated."
        )

    stats = run.stats or {}
    sev_counts = stats.get("findings_by_severity", {})
    exec_summary = (
        f"Assessment '{run.name}' evaluated {len(targets)} device(s) against "
        f"{meta.get('name', run.definition_id)} v{run.definition_version}. "
        f"Overall score: {score.get('overall', 'n/a')} "
        f"(coverage {score.get('coverage', 'n/a')}). "
        f"Findings: " + (
            ", ".join(f"{sev_counts.get(s, 0)} {s}" for s in _SEVERITY_ORDER
                      if sev_counts.get(s))
            or "none"
        ) + "."
    )

    return {
        "format_version": FORMAT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assessment": {
            "run_id": run.id,
            "name": run.name,
            "definition_id": run.definition_id,
            "definition_version": run.definition_version,
            "definition_name": meta.get("name"),
            "vendor": meta.get("vendor"),
            "product": meta.get("product"),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "status": run.status,
        },
        "executive_summary": exec_summary,
        "score": score,
        "stats": stats,
        "device_inventory": [
            {
                "device": t.device_name,
                "component_id": t.component_id,
                "status": t.status,
                "error": t.error,
            }
            for t in targets
        ],
        "collection_coverage": coverage_rows,
        "findings": findings,
        "control_results": [
            {
                "control_id": r.control_id,
                "title": r.title,
                "category": r.category,
                "severity": r.severity,
                "status": r.status,
                "method": r.method,
                "confidence": r.confidence,
                "device": target_names.get(r.target_id, r.target_id),
            }
            for r in results
        ],
        "limitations": limitations,
        "methodology": (
            "Deterministic collection of pre-defined read-only steps via the MCP "
            "gateway, followed by control evaluation with deterministic rules and "
            "parsers first and schema-validated LLM assistance only for controls "
            "declared hybrid/llm. Controls without sufficient evidence are excluded "
            "from the score denominator."
        ),
    }
