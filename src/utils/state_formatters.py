"""
Shared formatting utilities for converting GlobalState fields into
compact prompt-ready strings. Used by hypothesis.py, investigator.py,
and any future agent that needs scenario context.

All formatters accept a max_items parameter to control context size.
"""
from typing import Any, Dict, List, Optional


def format_topology_edges(topology_edges: List, max_items: int = 30) -> str:
    """Format topology edges into a readable graph representation."""
    if not topology_edges:
        return "No topology data available yet."
    lines = []
    for e in topology_edges[:max_items]:
        src = e.source_id if hasattr(e, "source_id") else e.get("source_id", "?")
        tgt = e.target_id if hasattr(e, "target_id") else e.get("target_id", "?")
        rel = e.relation if hasattr(e, "relation") else e.get("relation", "?")
        conf = e.confidence if hasattr(e, "confidence") else e.get("confidence", 0)
        lines.append(f"- {src} --[{rel}]--> {tgt} (confidence: {conf:.0%})")
    result = "\n".join(lines)
    if len(topology_edges) > max_items:
        result += f"\n... ({len(topology_edges) - max_items} more edges truncated)"
    return result


def format_baselines(client_context, max_items: int = 15) -> str:
    """Format baseline normal values from client context."""
    if not client_context:
        return "No baselines defined."
    baselines = (
        client_context.baselines
        if hasattr(client_context, "baselines")
        else client_context.get("baselines", [])
    )
    if not baselines:
        return "No baselines defined."
    lines = []
    for b in baselines[:max_items]:
        comp = b.component_id if hasattr(b, "component_id") else b.get("component_id", "?")
        metric = b.metric if hasattr(b, "metric") else b.get("metric", "?")
        val = b.normal_value if hasattr(b, "normal_value") else b.get("normal_value", "?")
        lines.append(f"- {comp}: {metric} = {val}")
    result = "\n".join(lines)
    if len(baselines) > max_items:
        result += f"\n... ({len(baselines) - max_items} more baselines truncated)"
    return result


def format_known_changes(client_context, max_items: int = 10) -> str:
    """Format recent known changes from client context."""
    if not client_context:
        return "No recent changes known."
    known_changes = (
        client_context.known_changes
        if hasattr(client_context, "known_changes")
        else client_context.get("known_changes", [])
    )
    if not known_changes:
        return "No recent changes known."
    lines = []
    for c in known_changes[:max_items]:
        date = c.date if hasattr(c, "date") else c.get("date", "?")
        desc = c.description if hasattr(c, "description") else c.get("description", "?")
        lines.append(f"- [{date}] {desc}")
    result = "\n".join(lines)
    if len(known_changes) > max_items:
        result += f"\n... ({len(known_changes) - max_items} more changes truncated)"
    return result


def format_facts(facts: Dict[str, Any], max_items: int = 25) -> str:
    """Format facts dictionary as key-value lines. Excludes internal keys."""
    if not facts:
        return "No specific facts collected yet."
    items = [(k, v) for k, v in facts.items() if not k.startswith("_")]
    if not items:
        return "No specific facts collected yet."
    lines = [f"- {k}: {v}" for k, v in items[:max_items]]
    result = "\n".join(lines)
    if len(items) > max_items:
        result += f"\n... ({len(items) - max_items} more facts truncated)"
    return result


def format_hypotheses(hypotheses: List, max_items: int = 10) -> str:
    """Format hypotheses list with id, status, summary, and rank."""
    if not hypotheses:
        return "No existing hypotheses."
    lines = []
    for h in hypotheses[:max_items]:
        lines.append(f"- [{h.id}] ({h.status}) {h.summary} (Rank: {h.rank})")
    result = "\n".join(lines)
    if len(hypotheses) > max_items:
        result += f"\n... ({len(hypotheses) - max_items} more hypotheses truncated)"
    return result


def format_path_analysis(path_analysis, max_breakpoints: int = 5) -> str:
    """Format path analysis breakpoints and missing evidence for context injection."""
    if not path_analysis:
        return ""
    parts = []
    breakpoints = (
        path_analysis.most_likely_breakpoints
        if hasattr(path_analysis, "most_likely_breakpoints")
        else path_analysis.get("most_likely_breakpoints", [])
    )
    missing = (
        path_analysis.missing_evidence
        if hasattr(path_analysis, "missing_evidence")
        else path_analysis.get("missing_evidence", [])
    )
    probes = (
        path_analysis.suggested_probes
        if hasattr(path_analysis, "suggested_probes")
        else path_analysis.get("suggested_probes", [])
    )
    if breakpoints:
        bp_lines = []
        for bp in breakpoints[:max_breakpoints]:
            edge = bp.get("edge", "?") if isinstance(bp, dict) else "?"
            constraint = bp.get("constraint", "?") if isinstance(bp, dict) else "?"
            reasoning = bp.get("reasoning", "") if isinstance(bp, dict) else ""
            bp_lines.append(f"- {edge} [{constraint}]: {reasoning}")
        parts.append("Breakpoints:\n" + "\n".join(bp_lines))
    if missing:
        parts.append("Missing evidence: " + "; ".join(missing[:5]))
    if probes:
        parts.append("Suggested probes: " + "; ".join(probes[:5]))
    return "\n".join(parts) if parts else ""


def format_open_questions(open_questions: List, max_items: int = 10) -> str:
    """Format open questions with status for context injection."""
    if not open_questions:
        return "No investigation questions defined."
    lines = []
    for q in open_questions[:max_items]:
        status = q.status if hasattr(q, "status") else q.get("status", "?")
        question = q.question if hasattr(q, "question") else q.get("question", "?")
        qid = q.id if hasattr(q, "id") else q.get("id", "?")
        lines.append(f"- [{qid}] ({status}) {question}")
    result = "\n".join(lines)
    if len(open_questions) > max_items:
        result += f"\n... ({len(open_questions) - max_items} more questions truncated)"
    return result


def format_evidence_summaries(evidence_refs: List, max_items: int = 10) -> str:
    """Format evidence reference summaries."""
    if not evidence_refs:
        return "No evidence gathered yet."
    lines = []
    for e in evidence_refs[-max_items:]:
        tool = e.tool_name if hasattr(e, "tool_name") else e.get("tool_name", "?")
        summary = e.summary if hasattr(e, "summary") else e.get("summary", "?")
        lines.append(f"- [{tool}]: {summary}")
    result = "\n".join(lines)
    if len(evidence_refs) > max_items:
        result = f"(showing last {max_items} of {len(evidence_refs)})\n" + result
    return result
