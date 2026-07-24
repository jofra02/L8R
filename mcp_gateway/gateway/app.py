"""Gateway assembly: discover vendor packs and expose the MCP server.

``gateway`` is the root FastMCP instance; ``app`` is the ASGI application
serving SSE at ``/sse/`` (compatible with the support_ai_agent MCP client and
the n8n "MCP Client Tool" node).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastmcp import FastMCP

from .admin_api import register_admin_routes
from .auth import get_auth_strategy
from .config import GATEWAY_ROOT, TenantRegistries, get_settings
from .routing_client import RoutingClient
from .spec_pipeline import build_appliance_server
from .vendor_pack import discover_packs

# Basic logging bootstrap so client hooks (gateway.http) reach the console
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

log = logging.getLogger("gateway.app")

VENDORS_ROOT = GATEWAY_ROOT / "vendors"


def build_gateway(vendors_root: Path = VENDORS_ROOT) -> FastMCP:
    settings = get_settings()
    gateway = FastMCP("MCP Gateway")

    packs = discover_packs(vendors_root)
    if not packs:
        log.warning("No appliance packs found — the gateway will expose no tools.")

    # Mount prefixes must be unique: two packs sharing a prefix would merge
    # their tool namespaces and silently shadow same-named tools.
    seen_prefixes: dict[str, str] = {}
    for pack in packs:
        other = seen_prefixes.get(pack.prefix)
        if other:
            raise RuntimeError(
                f"Duplicate mount prefix '{pack.prefix}' between packs "
                f"'{other}' and '{pack.qualified_name}'."
            )
        seen_prefixes[pack.prefix] = pack.qualified_name

    # One TenantRegistries per device_type (lazy per-tenant DeviceRegistry cache),
    # not bound to any single customer_id. Multiple versions of the same
    # appliance share the registry (same inventory), each under its own prefix.
    registries: dict[str, TenantRegistries] = {}
    for pack in packs:
        tenant_registries = registries.get(pack.manifest.device_type)
        if tenant_registries is None:
            tenant_registries = TenantRegistries(
                pack.manifest.device_type, default_tenant=settings.default_tenant
            )
            registries[pack.manifest.device_type] = tenant_registries
        client = RoutingClient(tenant_registries, get_auth_strategy(pack.manifest.auth), settings)
        appliance_server = build_appliance_server(pack, tenant_registries, client)
        gateway.mount(appliance_server, prefix=pack.prefix)
        log.info(f"Mounted appliance pack '{pack.qualified_name}' at prefix '{pack.prefix}'.")

    # Inventory admin API (HTTP routes only — adds no MCP tools)
    register_admin_routes(gateway, registries, packs, settings)

    return gateway


gateway = build_gateway()

# SSE transport at /sse/ — same endpoint contract as the original suite
app = gateway.http_app(path="/sse/", transport="sse")
