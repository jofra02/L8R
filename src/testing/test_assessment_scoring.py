"""Scoring engine: denominator exclusions, severity weights, coverage.

Run: uv run pytest src/testing/test_assessment_scoring.py
"""

from src.assessments.schema import ScoringConfig
from src.assessments.scoring import compute_score, compute_stats


def _row(status, severity="high", category="cat", target="t1"):
    return {"status": status, "severity": severity, "category": category, "target_id": target}


CONFIG = ScoringConfig()  # defaults: critical 10, high 5, medium 2, low 1; warning 0.5


def test_all_pass_scores_100():
    rows = [_row("pass"), _row("pass", "critical")]
    score = compute_score(rows, CONFIG)
    assert score["overall"] == 100.0
    assert score["coverage"] == 1.0


def test_not_evaluated_excluded_from_denominator():
    # 1 pass (high, weight 5) + 1 not_evaluated: score must be 100, not 50
    rows = [_row("pass"), _row("not_evaluated")]
    score = compute_score(rows, CONFIG)
    assert score["overall"] == 100.0
    assert score["evaluated"] == 1
    assert score["coverage"] == 0.5  # 1 evaluated of 2 applicable


def test_insufficient_evidence_is_not_a_fail():
    rows = [_row("pass"), _row("insufficient_evidence")]
    assert compute_score(rows, CONFIG)["overall"] == 100.0


def test_not_applicable_excluded_from_coverage_denominator():
    rows = [_row("pass"), _row("not_applicable")]
    score = compute_score(rows, CONFIG)
    assert score["overall"] == 100.0
    assert score["coverage"] == 1.0  # NA does not count as missing coverage


def test_severity_weights():
    # critical fail (10) + low pass (1) -> 1/11
    rows = [_row("fail", "critical"), _row("pass", "low")]
    score = compute_score(rows, CONFIG)
    assert score["overall"] == round(1 / 11 * 100, 1)


def test_warning_gets_half_credit():
    rows = [_row("warning")]
    assert compute_score(rows, CONFIG)["overall"] == 50.0


def test_zero_evaluated_edge():
    rows = [_row("not_evaluated"), _row("error")]
    score = compute_score(rows, CONFIG)
    assert score["overall"] is None
    assert score["coverage"] == 0.0


def test_per_category_and_per_target():
    rows = [
        _row("pass", category="A", target="t1"),
        _row("fail", category="B", target="t2"),
    ]
    score = compute_score(rows, CONFIG)
    assert score["by_category"]["A"]["score"] == 100.0
    assert score["by_category"]["B"]["score"] == 0.0
    assert score["by_target"]["t1"]["score"] == 100.0
    assert score["by_target"]["t2"]["score"] == 0.0


def test_stats_findings():
    rows = [
        _row("fail", "critical"), _row("warning", "medium"),
        _row("pass"), _row("insufficient_evidence"),
    ]
    stats = compute_stats(rows)
    assert stats["findings_total"] == 2
    assert stats["critical_findings"] == 1
    assert stats["by_status"]["insufficient_evidence"] == 1
