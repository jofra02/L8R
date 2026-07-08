"""Multi-tenant, multi-device HTTP client with per-request routing.

One ``RoutingClient`` serves all devices of a vendor pack across every tenant.
Every generated tool carries optional ``tenant`` and ``device`` header
parameters; ``send()`` resolves the tenant's registry, then the device within
it, rewrites the request URL (host/port) and swaps the auth headers, then
strips both routing headers before the request reaches the appliance. Without
a ``tenant`` header the optional ``default_tenant`` applies; without a
``device`` header the tenant's primary device applies.
"""

from __future__ import annotations

import logging
from typing import Dict

import httpx

from .auth import AuthStrategy
from .config import GatewaySettings, TenantRegistries

log = logging.getLogger("gateway.http")

# Placeholder when the inventory has no devices: tools still load (and keep
# their names/schemas), but un-routed calls fail with an obvious DNS error.
_UNCONFIGURED_HOST = "unconfigured.invalid"


async def _log_request(req: httpx.Request):
    log.info("--> %s %s", req.method, req.url)


async def _log_response(resp: httpx.Response):
    log.info("<-- %s %s", resp.status_code, resp.url)
    if resp.status_code != 200:
        await resp.aread()  # Body isn't loaded yet inside an event hook
        log.warning("Body[200B]: %s", resp.text[:200])


class RoutingClient(httpx.AsyncClient):
    def __init__(
        self,
        registries: TenantRegistries,
        auth: AuthStrategy,
        settings: GatewaySettings,
    ) -> None:
        # Note: httpx.AsyncClient owns `_auth`; use distinct names to avoid
        # having __init__ overwrite them.
        self._registries = registries
        self._auth_strategy = auth

        # No single tenant/primary at build time — the real host and auth are
        # always resolved per request in send(). base_url is only the fallback
        # for requests that resolve to no device (no tenant/no default/empty).
        super().__init__(
            base_url=f"https://{_UNCONFIGURED_HOST}:443",
            headers={"Content-Type": "application/json"},
            verify=False,
            timeout=httpx.Timeout(settings.http_timeout, connect=settings.http_connect_timeout),
            event_hooks={
                "request": [_log_request],
                "response": [_log_response],
            },
        )

    async def send(self, request: httpx.Request, *args, **kwargs) -> httpx.Response:
        """Intercept the final request to apply per-request (tenant, device) routing.

        Interception happens here (not in build_request) because FastMCP may
        build requests through different paths. Tenant is resolved first (header,
        else default_tenant), then the device within that tenant's live registry
        (header device, else the tenant's primary). Because resolution is
        per-request against the live registry, admin-API hot reloads — including
        primary changes — take effect without rebuilding the client; base_url
        only remains as the no-route fallback (unconfigured.invalid).
        """
        # Tenant selector (in: header). Alt spelling kept for manual use.
        target_tenant = None
        if "tenant" in request.headers:
            target_tenant = request.headers["tenant"]
            del request.headers["tenant"]  # Must not reach the appliance
        elif "x-customer-id" in request.headers:
            target_tenant = request.headers["x-customer-id"]
            del request.headers["x-customer-id"]

        # Device selector (in: header). Alt spelling kept for manual use.
        target_device_id = None
        if "device" in request.headers:
            target_device_id = request.headers["device"]
            del request.headers["device"]  # Must not reach the appliance
        elif "x-target-device" in request.headers:
            target_device_id = request.headers["x-target-device"]
            del request.headers["x-target-device"]

        registry = self._registries.get(target_tenant)
        if registry is None:
            log.warning(
                "Routing: no tenant resolved (header '%s', no default). Request unrouted.",
                target_tenant,
            )
            return await super().send(request, *args, **kwargs)

        device = None
        if target_device_id:
            device = registry.get(target_device_id)
            if not device:
                log.warning(
                    "Routing: device '%s' not found for tenant '%s'. Using primary.",
                    target_device_id,
                    registry.customer_id,
                )
        if device is None:
            device = registry.primary

        if device is not None:
            conn = registry.resolve_connection(device)
            host = conn.get("host")
            if host:
                port = int(conn.get("port", 443))

                # httpx.URL is immutable; swap scheme/host/port via copy_with
                request.url = request.url.copy_with(scheme="https", host=str(host), port=port)

                for name, value in self._auth_strategy.headers(conn).items():
                    request.headers[name] = value

                log.info(
                    "Routing: tenant '%s' device '%s' (host: %s)",
                    registry.customer_id,
                    device.id,
                    host,
                )

        return await super().send(request, *args, **kwargs)
