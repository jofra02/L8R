"""
Evaluate tool catalog quality from a JSON dump produced by dump_tool_catalog.py.

Runs 7 deterministic checks per tool and outputs a quality report.

Usage:
    uv run python scripts/evaluate_tool_catalog.py --input dump.json [--output report.json]
"""
import argparse
import json
import sys
from typing import Any

from src.core.registry import (
    _CATEGORY_KEYWORDS,
    _VENDOR_PATTERNS,
    _READ_METHODS,
    _WRITE_METHODS,
)

_WRITE_VERBS = {"create", "update", "delete", "modify", "set", "configure", "remove", "add", "write", "put", "post"}


def _has_write_verb(tool_name: str) -> list[str]:
    """Check for write verbs as whole segments in underscore-delimited tool names.
    Avoids false positives like 'setting' matching 'set' or 'address' matching 'add'.
    """
    segments = set(tool_name.lower().split("_"))
    return [v for v in _WRITE_VERBS if v in segments]


def _derive_category(tool_name: str, description: str) -> str:
    combined = f"{tool_name.lower()} {(description or '').lower()}"
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return cat
    return "general"


def _derive_vendor(tool_name: str, description: str) -> str:
    name_lower = tool_name.lower()
    desc_lower = (description or "").lower()
    for vendor, patterns in _VENDOR_PATTERNS.items():
        if any(p in name_lower or p in desc_lower for p in patterns):
            return vendor
    return ""


def _check_description_quality(tool: dict) -> dict:
    desc = (tool.get("description") or "").strip()
    name = tool.get("tool_name", "")
    if not desc or desc == name or len(desc) < 10:
        return {"status": "fail", "detail": f"length={len(desc)}, missing_or_trivial"}
    if len(desc) < 30:
        return {"status": "warn", "detail": f"length={len(desc)}, short"}
    return {"status": "pass", "detail": f"length={len(desc)}"}


def _check_param_descriptions(tool: dict) -> dict:
    schema = tool.get("args_schema") or {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    if not properties:
        return {"status": "pass", "detail": "no_params"}

    missing_required = []
    missing_optional = []
    for pname, pdef in properties.items():
        desc = (pdef.get("description") or "").strip()
        if not desc:
            if pname in required:
                missing_required.append(pname)
            else:
                missing_optional.append(pname)

    if missing_required:
        return {"status": "fail", "detail": f"required_missing_desc: {missing_required}"}
    if missing_optional:
        return {"status": "warn", "detail": f"optional_missing_desc: {missing_optional}"}
    return {"status": "pass", "detail": "all_params_described"}


def _check_required_optional_marking(tool: dict) -> dict:
    schema = tool.get("args_schema") or {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    if not properties:
        return {"status": "pass", "detail": "no_params"}

    total = len(properties)
    req_count = len(required)

    if req_count == total:
        return {"status": "warn", "detail": f"all_{total}_params_required"}
    if req_count == 0 and total > 0:
        return {"status": "warn", "detail": f"zero_required_of_{total}_params"}
    return {"status": "pass", "detail": f"{req_count}_required_of_{total}"}


def _check_category_accuracy(tool: dict) -> dict:
    stored = tool.get("category", "general")
    derived = _derive_category(tool.get("tool_name", ""), tool.get("description", ""))

    if derived != stored:
        return {"status": "fail", "detail": f"stored={stored}, derived={derived}"}
    if stored == "general" and derived == "general":
        # Check if there are keywords that could match
        combined = f"{tool.get('tool_name', '').lower()} {(tool.get('description') or '').lower()}"
        for cat, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in combined for kw in keywords):
                return {"status": "warn", "detail": f"general_but_has_keywords_for={cat}"}
    return {"status": "pass", "detail": f"category={stored}"}


def _check_vendor_detection(tool: dict) -> dict:
    stored = tool.get("vendor", "")
    if stored:
        return {"status": "pass", "detail": f"vendor={stored}"}

    derived = _derive_vendor(tool.get("tool_name", ""), tool.get("description", ""))
    if derived:
        return {"status": "warn", "detail": f"empty_vendor_but_keywords_suggest={derived}"}
    return {"status": "pass", "detail": "no_vendor_applicable"}


def _check_method_read_only(tool: dict) -> dict:
    name_lower = tool.get("tool_name", "").lower()
    stored_ro = str(tool.get("read_only", "")).lower() in ("true", "1")

    stored_method = tool.get("method", "unknown")
    desc_first = (tool.get("description") or "").strip().split(" ")[0].lower()

    # Only check name segments for write verbs if method is not already "get"
    matched_verbs = []
    if stored_method != "get":
        matched_verbs = _has_write_verb(tool.get("tool_name", ""))

    # Description prefix is a strong signal regardless of method
    if desc_first in ("create", "delete", "update", "remove", "modify"):
        matched_verbs = matched_verbs or [f"desc:{desc_first}"]

    if stored_ro and matched_verbs:
        return {"status": "fail", "detail": f"read_only=true but write signal: {matched_verbs}"}

    # Re-derive method for mismatch check (mirrors registry logic)
    derived_method = "unknown"
    for m in (*_READ_METHODS, *_WRITE_METHODS):
        if name_lower.startswith(m + "_") or name_lower == m:
            derived_method = m
            break
    if derived_method == "unknown":
        for m in (*_WRITE_METHODS, *_READ_METHODS):
            if name_lower.endswith("_" + m):
                derived_method = m
                break
    if derived_method == "unknown":
        best_pos = -1
        for m in (*_READ_METHODS, *_WRITE_METHODS):
            pos = name_lower.rfind(f"_{m}_")
            if pos > best_pos:
                best_pos = pos
                derived_method = m

    derived_ro = derived_method in _READ_METHODS or derived_method == "unknown"
    # Description prefix override
    if derived_ro and derived_method == "unknown" and desc_first in ("create", "delete", "update", "remove", "modify"):
        derived_ro = False
    if stored_ro != derived_ro:
        return {"status": "warn", "detail": f"stored_ro={stored_ro}, derived_ro={derived_ro} (method: stored={stored_method}, derived={derived_method})"}

    return {"status": "pass", "detail": f"read_only={stored_ro}, method={stored_method}"}


def _check_embed_text_quality(tool: dict) -> dict:
    text = (tool.get("page_content") or "").strip()
    length = len(text)

    if length < 20:
        return {"status": "fail", "detail": f"page_content_length={length}, too_short"}

    issues = []
    if length < 50:
        issues.append(f"short({length})")
    unique_words = set(text.lower().split())
    if len(unique_words) < 8:
        issues.append(f"low_unique_words({len(unique_words)})")
    if "Parameters:" not in text and "parameters:" not in text.lower():
        issues.append("missing_parameters_section")

    if issues:
        return {"status": "warn", "detail": "; ".join(issues)}
    return {"status": "pass", "detail": f"length={length}, unique_words={len(unique_words)}"}


_ALL_CHECKS = [
    ("description_quality", _check_description_quality),
    ("param_descriptions", _check_param_descriptions),
    ("required_optional_marking", _check_required_optional_marking),
    ("category_accuracy", _check_category_accuracy),
    ("vendor_detection", _check_vendor_detection),
    ("method_read_only", _check_method_read_only),
    ("embed_text_quality", _check_embed_text_quality),
]


def evaluate(tools: list[dict]) -> dict:
    summary_checks = {name: {"pass": 0, "warn": 0, "fail": 0} for name, _ in _ALL_CHECKS}
    tool_results = []
    critical_tools = []

    for tool in tools:
        tool_name = tool.get("tool_name", "unknown")
        checks = {}
        fail_count = 0
        worst = "pass"

        for check_name, check_fn in _ALL_CHECKS:
            result = check_fn(tool)
            checks[check_name] = result
            status = result["status"]
            summary_checks[check_name][status] += 1

            if status == "fail":
                fail_count += 1
                worst = "fail"
            elif status == "warn" and worst != "fail":
                worst = "warn"

        tool_results.append({
            "tool_name": tool_name,
            "overall": worst,
            "checks": checks,
        })

        if fail_count >= 2:
            critical_tools.append(tool_name)

    tools_with_issues = sum(1 for t in tool_results if t["overall"] != "pass")

    return {
        "summary": {
            "total_tools": len(tools),
            "tools_with_issues": tools_with_issues,
            "critical_tools": critical_tools,
            "checks": summary_checks,
        },
        "tools": tool_results,
    }


def print_summary(report: dict):
    s = report["summary"]
    print(f"\n{'='*60}")
    print(f"Tool Catalog Quality Report")
    print(f"{'='*60}")
    print(f"Total tools:       {s['total_tools']}")
    print(f"Tools with issues: {s['tools_with_issues']}")
    print(f"Critical (2+ fail): {len(s['critical_tools'])}")
    print()

    print(f"{'Check':<28} {'Pass':>6} {'Warn':>6} {'Fail':>6}")
    print(f"{'-'*28} {'-'*6} {'-'*6} {'-'*6}")
    for check_name, counts in s["checks"].items():
        print(f"{check_name:<28} {counts['pass']:>6} {counts['warn']:>6} {counts['fail']:>6}")

    if s["critical_tools"]:
        print(f"\nCritical tools:")
        for name in s["critical_tools"]:
            print(f"  - {name}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Evaluate tool catalog quality")
    parser.add_argument("--input", required=True, help="Path to tool catalog dump JSON")
    parser.add_argument("--output", default=None, help="Output report JSON path")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        tools = json.load(f)

    report = evaluate(tools)

    output_path = args.output or args.input.replace(".json", "_report.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print_summary(report)
    print(f"Full report: {output_path}")


if __name__ == "__main__":
    main()
