"""Generic OpenAPI spec fixes applied before tool generation.

Vendor-specific transforms (e.g. FortiOS SD-WAN monolith split) live in each
vendor pack's ``hooks.py`` and run after the generic fixes via ``extra_fixes``.
"""

import copy
import hashlib
import logging
import re
from typing import Callable, Iterable, Sequence

logger = logging.getLogger(__name__)

SpecFix = Callable[[dict], dict]


def apply_fixes(spec: dict, extra_fixes: Sequence[SpecFix] = ()) -> dict:
    """Apply the generic fixes, then any vendor-provided ones, in order."""
    spec = _resolve_parameter_refs(spec)
    spec = _strip_ghost_parameters(spec)
    spec = _deduplicate_parameters(spec)
    spec = _enrich_summaries(spec)
    for fix in extra_fixes:
        spec = fix(spec)
    return spec


def sanitize_operation_ids(spec: dict, prefix: str, stopwords: Iterable[str] = ()) -> dict:
    """Enforce the 64-character limit on tool names by rewriting operationIds.

    Logic:
    1. Redundancy removal: strip prefix tokens repeated inside the opId.
    2. Stopword removal: drop vendor-declared filler tokens.
    3. Hashing: if still too long, truncate and append a deterministic hash.

    NAME-FREEZE WARNING: the 64-char budget is computed against
    ``prefix + "_" + opId`` where ``prefix`` is only the spec-level mount name
    (e.g. ``firewall``), NOT the full mounted chain (``fgt_cmdb_firewall_...``).
    Final tool names can therefore exceed 64 chars — that is the historical
    behavior the Qdrant tool_catalog was indexed against. Do NOT "fix" this
    budget: it would rename every hash-truncated tool and force a re-index.
    """
    # HTTP verbs preserved at the start of an opId
    verbs = {"get", "put", "post", "delete", "patch", "head", "options"}

    stopwords = set(stopwords)

    for path, path_item in spec.get("paths", {}).items():
        for method, op in path_item.items():
            if method not in verbs and method != "parameters":
                continue
            if "operationId" not in op:
                continue

            original_op_id = op["operationId"]

            # FastMCP will prepend "{prefix}_" to the tool name, so the op_id
            # budget is:
            max_op_len = 64 - len(prefix) - 1

            # --- Stage 1: smart redundancy removal ---
            # e.g. prefix="vpn_cert", op="get_vpn_cert_details" -> "get_details"
            prefix_tokens = prefix.split("_")
            op_tokens = original_op_id.split("_")

            # Preserve the verb when present
            verb_found = None
            if op_tokens and op_tokens[0].lower() in verbs:
                verb_found = op_tokens.pop(0)

            # Drop tokens that repeat the prefix or are stopwords
            clean_tokens = [t for t in op_tokens if t not in prefix_tokens and t not in stopwords]

            if verb_found:
                clean_tokens.insert(0, verb_found)

            stage1_op_id = "_".join(clean_tokens)

            candidate_op_id = stage1_op_id if stage1_op_id else original_op_id

            current_full_name = f"{prefix}_{candidate_op_id}"

            if len(current_full_name) <= 64:
                op["operationId"] = candidate_op_id
                if candidate_op_id != original_op_id:
                    logger.info(f"Sanitized (Redundancy): {original_op_id} -> {candidate_op_id}")
                continue

            # --- Stage 2: deterministic hash fallback ---
            # Hash the full (over-budget) name so the suffix is stable
            full_hash = hashlib.md5(current_full_name.encode()).hexdigest()[:4]

            # prefix + "_" + {base} + "_" + {hash} <= 64
            allowance = 64 - len(prefix) - 6

            if allowance < 5:
                allowance = 5

            truncated_base = stage1_op_id[:allowance].rstrip("_")

            final_op_id = f"{truncated_base}_{full_hash}"

            op["operationId"] = final_op_id
            logger.info(f"Sanitized (Hash): {original_op_id} -> {final_op_id}")

    return spec


def _resolve_parameter_refs(spec: dict) -> dict:
    """Inline-resolve $ref pointers in operation parameters.

    Handles both OpenAPI 3.x (#/components/parameters/X) and
    Swagger 2.0 (#/parameters/X) style refs.
    """
    ref_map = {}
    for key, val in spec.get("components", {}).get("parameters", {}).items():
        ref_map[f"#/components/parameters/{key}"] = val
    for key, val in spec.get("parameters", {}).items():
        ref_map[f"#/parameters/{key}"] = val

    if not ref_map:
        return spec

    resolved = 0
    for path, path_item in spec.get("paths", {}).items():
        for method, op in path_item.items():
            if not isinstance(op, dict) or "parameters" not in op:
                continue
            new_params = []
            for p in op["parameters"]:
                ref = p.get("$ref")
                if ref and ref in ref_map:
                    new_params.append(copy.deepcopy(ref_map[ref]))
                    resolved += 1
                else:
                    new_params.append(p)
            op["parameters"] = new_params

    if resolved:
        logger.info(f"Resolved {resolved} parameter $refs")
    return spec


# Patterns that indicate a generic, unhelpful CMDB summary
_GENERIC_SUMMARY_PATTERNS = [
    re.compile(r"^Select a specific entry from a CLI table"),
    re.compile(r"^Select all entries in a CLI table"),
    re.compile(r"^Create object\(s\) in this table"),
    re.compile(r"^Update this specific resource"),
    re.compile(r"^Delete this specific resource"),
]

_METHOD_ACTION_MAP = {
    "get": "Get",
    "put": "Update",
    "post": "Create",
    "delete": "Delete",
}


def _strip_ghost_parameters(spec: dict) -> dict:
    """Remove parameters whose name or location is missing/empty.

    These are auto-generation artifacts that break FastMCP schema generation.
    """
    stripped = 0
    for path, path_item in spec.get("paths", {}).items():
        for method, op in path_item.items():
            if not isinstance(op, dict) or "parameters" not in op:
                continue
            original = op["parameters"]
            cleaned = [
                p for p in original
                if p.get("name") and p.get("in")
            ]
            removed = len(original) - len(cleaned)
            if removed:
                op["parameters"] = cleaned
                stripped += removed
    if stripped:
        logger.info(f"Stripped {stripped} ghost parameters")
    return spec


def _deduplicate_parameters(spec: dict) -> dict:
    """Remove duplicate parameters (same name + in) within an operation.

    Keeps the first occurrence.
    """
    deduped = 0
    for path, path_item in spec.get("paths", {}).items():
        for method, op in path_item.items():
            if not isinstance(op, dict) or "parameters" not in op:
                continue
            seen = set()
            unique = []
            for p in op["parameters"]:
                key = (p.get("name"), p.get("in"))
                if key in seen:
                    deduped += 1
                    continue
                seen.add(key)
                unique.append(p)
            if len(unique) < len(op["parameters"]):
                op["parameters"] = unique
    if deduped:
        logger.info(f"Deduplicated {deduped} parameters")
    return spec


def _enrich_summaries(spec: dict) -> dict:
    """Replace generic CMDB summaries with ones derived from tag descriptions.

    "Select all entries in a CLI table" becomes "List — Configure DHCP servers"
    using the operation tag's description.
    """
    tag_map = {}
    for tag in spec.get("tags", []):
        name = tag.get("name")
        desc = tag.get("description")
        if name and desc:
            tag_map[name] = desc.strip().rstrip(".")

    if not tag_map:
        return spec

    enriched = 0
    for path, path_item in spec.get("paths", {}).items():
        for method, op in path_item.items():
            if not isinstance(op, dict) or "summary" not in op:
                continue

            summary = op["summary"]

            is_generic = any(p.search(summary) for p in _GENERIC_SUMMARY_PATTERNS)
            if not is_generic:
                continue

            op_tags = op.get("tags", [])
            tag_desc = None
            for t in op_tags:
                if t in tag_map:
                    tag_desc = tag_map[t]
                    break

            if not tag_desc:
                continue

            action = _METHOD_ACTION_MAP.get(method, method.upper())
            # For GET, distinguish list vs single entry
            if method == "get" and "Select all" in summary:
                action = "List"

            op["summary"] = f"{action} — {tag_desc}"
            enriched += 1

    if enriched:
        logger.info(f"Enriched {enriched} generic summaries")
    return spec
