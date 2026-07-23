#!/usr/bin/env python
"""Convert the raw FortiEDR Swagger 2.0 exports to OpenAPI 3.0.3 pack specs.

Source:  FortiEDR/swagger/v6.2/fortiedr-openapi-<area>.json  (Springfox exports)
Output:  vendors/fortinet/fortiedr/specs/mgmt/fortiedr_<area>.json

Usage:
    uv run python scripts/convert_fortiedr_specs.py            # write specs
    uv run python scripts/convert_fortiedr_specs.py --check    # verify no drift

NAME-FREEZE WARNING: the operationId algorithm below defines the frozen
``fedr_*`` tool names in baseline_tools.txt. It is a pure function of
``(method, path)`` — re-running the converter on the same inputs is
byte-identical. Changing the algorithm, READ_EXEMPT, or OVERRIDES after the
baseline is committed RENAMES TOOLS and forces a Qdrant re-index.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway import schema_fixes  # noqa: E402

GATEWAY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = GATEWAY_ROOT / "FortiEDR" / "swagger" / "v6.2"
DEFAULT_DST = GATEWAY_ROOT / "vendors" / "fortinet" / "fortiedr" / "specs" / "mgmt"

RAW_PREFIX = "fortiedr-openapi-"
CONTROLLER_SUFFIX = "_rest_api_controller"
GROUP = "mgmt"
PACK_PREFIX = "fedr"

HTTP_METHODS = {"get", "post", "put", "delete", "patch"}

# Mirror of the app-side name filter: src/config.py SAFETY_BLOCKED_KEYWORDS
# (name-matchable subset) + SAFETY_BLOCKED_NAME_KEYWORDS. Keep in sync — the
# converter guarantees every non-exempt mutating tool name contains one of
# these, which is what makes app-side filtering sound.
BLOCKED_NAME_KEYWORDS = [
    # from SAFETY_BLOCKED_KEYWORDS (substrings that can occur in tool names)
    "delete", "execute", "configure", "shutdown", "reboot", "truncate",
    "format", "destroy", "purge", "deploy", "push", "publish", "migrate",
    # SAFETY_BLOCKED_NAME_KEYWORDS
    "update", "create", "upload", "upgrade", "isolate", "uninstall",
    "remediate", "terminate", "set_", "reset", "assign", "clone",
    "transfer", "import", "toggle", "release", "move", "stop",
]

MUTATING_VERB = {"post": "create", "put": "update", "delete": "delete"}

# Mutating-method operations deliberately exposed as safe reads (no verb
# prefix, so no blocked keyword lands in the tool name). Reviewed allowlist —
# additions/removals after the baseline commit rename tools.
READ_EXEMPT = {
    ("threat_hunting", "post", "/management-rest/threat-hunting/search"),
    ("threat_hunting", "post", "/management-rest/threat-hunting/counts"),
    ("threat_hunting", "post", "/management-rest/threat-hunting/facets"),
    ("dashboard", "post", "/api/dashboard/generate-report"),
    ("incidents", "post", "/api/incidents/generate-report"),
}

# Hard operationId overrides for operations the algorithm would mislabel.
# iot-last-discovery: the Springfox handler is named "stop-last-discovery" —
# treated as a side-effect GET and named so the safety filter blocks it.
OVERRIDES = {
    ("admin", "get", "/api/admin/settings/iot-last-discovery"): "stop_last_discovery",
}

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def derive_area(stem: str) -> str:
    area = stem.replace(RAW_PREFIX, "").replace("-", "_")
    if area.endswith(CONTROLLER_SUFFIX):
        area = area[: -len(CONTROLLER_SUFFIX)]
    return area


def _norm_segment(seg: str) -> str:
    """``{incidentId}`` -> ``incident_id``; ``av-scan`` -> ``av_scan``."""
    seg = seg.strip("{}")
    seg = _CAMEL_RE.sub("_", seg)
    return seg.replace("-", "_").lower()


def build_operation_id(area: str, method: str, path: str) -> str:
    override = OVERRIDES.get((area, method, path))
    if override:
        return override

    segments = [s for s in path.split("/") if s]
    if segments and segments[0] in ("api", "management-rest"):
        segments = segments[1:]
    tokens = []
    for seg in segments:
        tokens.extend(t for t in _norm_segment(seg).split("_") if t)

    name = "_".join(tokens)

    if method == "get":
        if "get" not in tokens:
            tokens = ["get"] + tokens
    elif (area, method, path) not in READ_EXEMPT:
        if not any(kw in name for kw in BLOCKED_NAME_KEYWORDS):
            tokens = [MUTATING_VERB[method]] + tokens

    # Collapse consecutive duplicate tokens (e.g. get_get_audit -> get_audit)
    collapsed = [t for i, t in enumerate(tokens) if i == 0 or t != tokens[i - 1]]
    return "_".join(collapsed)


# ── Swagger 2.0 -> OpenAPI 3.0.3 ─────────────────────────────────────────────

_PARAM_SCHEMA_FIELDS = (
    "type", "format", "items", "default", "enum", "maximum", "minimum",
    "exclusiveMaximum", "exclusiveMinimum", "maxLength", "minLength",
    "pattern", "maxItems", "minItems", "uniqueItems", "multipleOf",
)


def _convert_schema(schema):
    """Recursively rewrite refs and Swagger-only types inside a schema."""
    if isinstance(schema, list):
        return [_convert_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, val in schema.items():
        if key == "$ref" and isinstance(val, str):
            out[key] = val.replace("#/definitions/", "#/components/schemas/")
        elif key == "collectionFormat":
            continue  # Swagger 2 only; serialization handled at param level
        else:
            out[key] = _convert_schema(val)
    if out.get("type") == "file":
        out["type"] = "string"
        out["format"] = "binary"
    return out


def _convert_parameter(param: dict) -> dict:
    out = {k: param[k] for k in ("name", "in", "description", "required", "allowEmptyValue") if k in param}
    schema = {k: param[k] for k in _PARAM_SCHEMA_FIELDS if k in param}
    out["schema"] = _convert_schema(schema)
    if param.get("collectionFormat") == "multi":
        out["style"] = "form"
        out["explode"] = True
    return out


def _build_request_body(body_params: list, form_params: list) -> dict:
    if body_params:
        body = body_params[0]  # Swagger 2 allows at most one
        request_body = {"content": {"application/json": {"schema": _convert_schema(body.get("schema", {}))}}}
        if body.get("description"):
            request_body["description"] = body["description"]
        if body.get("required"):
            request_body["required"] = True
        return request_body

    properties = {}
    required = []
    for param in form_params:
        schema = {k: param[k] for k in _PARAM_SCHEMA_FIELDS if k in param}
        if param.get("description"):
            schema["description"] = param["description"]
        properties[param["name"]] = _convert_schema(schema)
        if param.get("required"):
            required.append(param["name"])
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    media_type = (
        "multipart/form-data"
        if any(p.get("type") == "file" for p in form_params)
        else "application/x-www-form-urlencoded"
    )
    return {"content": {media_type: {"schema": schema}}}


def _convert_responses(responses: dict) -> dict:
    out = {}
    for code, resp in responses.items():
        new_resp = {k: v for k, v in resp.items() if k not in ("schema", "headers")}
        if "headers" in resp:
            new_resp["headers"] = {
                name: {"schema": _convert_schema({k: v for k, v in hdr.items() if k != "description"}),
                       **({"description": hdr["description"]} if "description" in hdr else {})}
                for name, hdr in resp["headers"].items()
            }
        if "schema" in resp:
            new_resp["content"] = {"application/json": {"schema": _convert_schema(resp["schema"])}}
        out[code] = new_resp
    return out


def _convert_operation(area: str, method: str, path: str, op: dict) -> dict:
    out = {k: v for k, v in op.items() if k not in (
        "operationId", "parameters", "responses", "produces", "consumes", "schemes",
    )}
    out["operationId"] = build_operation_id(area, method, path)

    params = op.get("parameters", [])
    body_params = [p for p in params if p.get("in") == "body"]
    form_params = [p for p in params if p.get("in") == "formData"]
    plain_params = [p for p in params if p.get("in") not in ("body", "formData")]

    if plain_params:
        out["parameters"] = [_convert_parameter(p) for p in plain_params]
    if body_params or form_params:
        out["requestBody"] = _build_request_body(body_params, form_params)
    out["responses"] = _convert_responses(op.get("responses", {}))
    return out


def swagger2_to_openapi3(raw: dict, area: str) -> dict:
    spec = {
        "openapi": "3.0.3",
        "info": dict(raw.get("info", {})),
        "servers": [{"url": "/"}],
    }
    spec["info"]["version"] = "6.2"
    if raw.get("tags"):
        spec["tags"] = raw["tags"]

    paths = {}
    for path, item in raw.get("paths", {}).items():
        new_item = {}
        for method, op in item.items():
            if method in HTTP_METHODS:
                new_item[method] = _convert_operation(area, method, path, op)
            else:
                new_item[method] = _convert_schema(op)
        paths[path] = new_item
    spec["paths"] = paths

    components = {"securitySchemes": {"basicAuth": {"type": "http", "scheme": "basic"}}}
    if raw.get("definitions"):
        components["schemas"] = {
            name: _convert_schema(schema) for name, schema in raw["definitions"].items()
        }
    spec["components"] = components
    spec["security"] = [{"basicAuth": []}]
    return spec


# ── Verification against the real gateway sanitizer ──────────────────────────

def verify_final_names(spec: dict, mount: str, area: str) -> list[str]:
    """Run the converted spec through the gateway sanitizer and assert the
    tool-name safety invariants. Returns the full sanitized tool names."""
    sanitized = schema_fixes.sanitize_operation_ids(copy.deepcopy(spec), mount, stopwords=[])
    errors = []
    names = []
    for path, item in sanitized["paths"].items():
        for method, op in item.items():
            if method not in HTTP_METHODS:
                continue
            full = f"{PACK_PREFIX}_{GROUP}_{mount}_{op['operationId']}".lower()
            names.append(full)
            key = (area, method, path)
            if key in READ_EXEMPT:
                continue
            blocked = any(kw in full for kw in BLOCKED_NAME_KEYWORDS)
            if method == "get" and key not in OVERRIDES:
                if "_get" not in full:
                    errors.append(f"GET without _get marker: {method.upper()} {path} -> {full}")
            elif method == "get":  # overridden side-effect GET must be blocked
                if not blocked:
                    errors.append(f"Overridden GET not blocked: {method.upper()} {path} -> {full}")
            elif not blocked:
                errors.append(f"Mutating op without blocked keyword: {method.upper()} {path} -> {full}")
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        errors.append(f"Duplicate sanitized tool names: {sorted(duplicates)}")
    if errors:
        raise SystemExit(f"[{area}] name verification failed:\n  " + "\n  ".join(errors))
    return names


def serialize(spec: dict) -> str:
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert FortiEDR Swagger 2.0 specs to OpenAPI 3.0.3")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--dst", type=Path, default=DEFAULT_DST)
    parser.add_argument("--check", action="store_true", help="Verify existing output matches (no writes)")
    args = parser.parse_args()

    raw_files = sorted(args.src.glob(f"{RAW_PREFIX}*.json"))
    if not raw_files:
        raise SystemExit(f"No {RAW_PREFIX}*.json files found in {args.src}")

    all_names: list[str] = []
    drift: list[str] = []
    written = 0
    for raw_path in raw_files:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        area = derive_area(raw_path.stem)
        mount = area  # matches vendor_pack.spec_mount_name with name_strips=[fortiedr_]
        spec = swagger2_to_openapi3(raw, area)
        all_names.extend(verify_final_names(spec, mount, area))

        out_path = args.dst / f"fortiedr_{area}.json"
        content = serialize(spec)
        if args.check:
            existing = out_path.read_text(encoding="utf-8") if out_path.exists() else None
            if existing != content:
                drift.append(out_path.name)
        else:
            args.dst.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            written += 1

    duplicates = {n for n in all_names if all_names.count(n) > 1}
    if duplicates:
        raise SystemExit(f"Cross-file duplicate tool names: {sorted(duplicates)}")

    gets = sum(1 for n in all_names if "_get" in n)
    blocked = sum(1 for n in all_names if any(kw in n for kw in BLOCKED_NAME_KEYWORDS))
    print(f"{len(raw_files)} specs, {len(all_names)} operations "
          f"({gets} with _get marker, {blocked} safety-blocked names)")
    if args.check:
        if drift:
            raise SystemExit(f"Drift detected in {len(drift)} files: {', '.join(drift)}")
        print("check OK — output matches converter")
    else:
        print(f"{written} files written to {args.dst}")


if __name__ == "__main__":
    main()
