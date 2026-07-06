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

from .auth import get_auth_strategy
from .config import DeviceRegistry, GATEWAY_ROOT, get_settings
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

    for pack in packs:
        registry = DeviceRegistry(settings.active_customer_id, pack.manifest.device_type)
        client = RoutingClient(registry, get_auth_strategy(pack.manifest.auth), settings)
        appliance_server = build_appliance_server(pack, registry, client)
        gateway.mount(appliance_server, prefix=pack.prefix)
        log.info(f"Mounted appliance pack '{pack.qualified_name}' at prefix '{pack.prefix}'.")

    return gateway


gateway = build_gateway()

# SSE transport at /sse/ — same endpoint contract as the original suite
app = gateway.http_app(path="/sse/", transport="sse")
