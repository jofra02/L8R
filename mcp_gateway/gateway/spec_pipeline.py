"""OpenAPI → MCP build pipeline for one appliance pack.

For each group directory under ``vendors/<vendor>/<appliance>/specs/`` a
sub-server is created; every spec file in it becomes a mounted FastMCP server
whose tools are the spec's operations. Tool names follow the mount chain:

    {pack.prefix}_{group}_{spec_mount_name}_{operationId}

NAME-FREEZE: the transformation order below replicates the original
fortinet_ai_suite fgt_mcp loader exactly (fixes → sanitize → basePath →
device header injection → parameter doc appends → from_openapi → mount).
Reordering any step can silently rename tools and invalidate the Qdrant
tool_catalog index. ``mcp_gateway/baseline_tools.txt`` + the name-freeze test
guard this contract.
"""

from __future__ import annotations

import json
import logging
import traceback

from fastmcp import FastMCP

from . import schema_fixes
from .config import TenantRegistries
from .middleware import TracingMiddleware
from .routing_client import RoutingClient
from .vendor_pack import AppliancePack

log = logging.getLogger("gateway.pipeline")

_HTTP_METHODS = ("get", "post", "put", "delete", "patch")


def build_appliance_server(
    pack: AppliancePack,
    registries: TenantRegistries,
    client: RoutingClient,
) -> FastMCP:
    """Build the FastMCP server tree for an appliance pack."""
    appliance_server = FastMCP(pack.manifest.display_name)
    appliance_server.add_middleware(TracingMiddleware())

    if not pack.specs_dir.exists():
        log.warning(f"Pack '{pack.qualified_name}': specs directory missing at {pack.specs_dir}")
        return appliance_server

    for subdir in sorted(p for p in pack.specs_dir.iterdir() if p.is_dir()):
        group_name = subdir.name.lower()  # e.g. monitor | cmdb | log
        group_server = FastMCP(f"{pack.manifest.display_name} {group_name.capitalize()} API")

        for spec_path in sorted(subdir.glob(pack.manifest.spec_glob)):
            safe_name = pack.spec_mount_name(spec_path, group_name)

            try:
                with spec_path.open(encoding="utf-8") as fh:
                    spec = json.load(fh)

                # Generic schema fixes, then vendor hooks (e.g. SD-WAN split)
                spec = schema_fixes.apply_fixes(spec, extra_fixes=pack.spec_fixes)

                # Enforce tool name limits (sanitize operationIds)
                spec = schema_fixes.sanitize_operation_ids(
                    spec, safe_name, stopwords=pack.manifest.sanitizer_stopwords
                )

                # ── determine the real URL prefix ────────────────────────────
                base_prefix = spec.get("basePath")               # OpenAPI 2
                if not base_prefix and "servers" in spec:        # OpenAPI 3
                    base_prefix = spec["servers"][0].get("url", "")
                base_prefix = (base_prefix or "").rstrip("/")
                if not base_prefix.startswith("/"):
                    base_prefix = f"/{base_prefix}"

                # ── inject the prefix into paths + enrich operations ─────────
                fixed_paths = {}
                for p, val in spec["paths"].items():
                    fixed_paths[p if p.startswith(base_prefix) else f"{base_prefix}{p}"] = val

                    for method, op_spec in val.items():
                        if method not in _HTTP_METHODS:
                            continue

                        if "parameters" not in op_spec:
                            op_spec["parameters"] = []

                        # 1. Inject the 'device' routing parameter (header)
                        if not any(param.get("name") == "device" for param in op_spec["parameters"]):
                            op_spec["parameters"].append({
                                "name": "device",
                                "in": "header",
                                "schema": {"type": "string"},
                                "required": False,
                                "description": pack.manifest.device_param_description,
                            })

                        # 1b. Inject the 'tenant' routing parameter (header).
                        # Framework-supplied by the caller (never the LLM); the
                        # gateway resolves the tenant's inventory per request.
                        # Params do not affect tool names — name-freeze safe.
                        if not any(param.get("name") == "tenant" for param in op_spec["parameters"]):
                            op_spec["parameters"].append({
                                "name": "tenant",
                                "in": "header",
                                "schema": {"type": "string"},
                                "required": False,
                                "description": (
                                    "Target tenant/customer_id whose inventory to route "
                                    "against. Supplied automatically by the platform."
                                ),
                            })

                        # 2. Append vendor-provided help to matching parameters
                        for param in op_spec["parameters"]:
                            extra_doc = pack.parameter_doc_appends.get(param.get("name"))
                            if not extra_doc:
                                continue
                            current_desc = param.get("description", "")
                            # Avoid duplicating on re-runs
                            if extra_doc not in current_desc:
                                param["description"] = current_desc + extra_doc

                spec["paths"] = fixed_paths

                sub = FastMCP.from_openapi(
                    openapi_spec=spec,
                    client=client,
                    name=None,
                )
                group_server.mount(sub, prefix=safe_name)

            except Exception as e:
                log.error(f"ERROR loading {spec_path.name}: {e}")
                traceback.print_exc()

        appliance_server.mount(group_server, prefix=group_name)

    if pack.manifest.inventory_tool:
        _register_inventory_tool(appliance_server, registries)

    return appliance_server


def _register_inventory_tool(appliance_server: FastMCP, registries: TenantRegistries) -> None:
    @appliance_server.tool()
    def get_inventory_tree(tenant: str = "") -> str:
        """
        Returns a tree structure of the available inventory devices.
        Use this to find valid 'device' names for other tools.
        """
        registry = registries.get(tenant or None)
        if registry is None or not registry.devices:
            return "No devices found in inventory."

        summary = ["Available Devices:"]
        for dev_id, dev in registry.devices.items():
            summary.append(f"- {dev_id} (Name: {dev.name}, IP: {dev.connection.get('host', 'N/A')})")

        return "\n".join(summary)
