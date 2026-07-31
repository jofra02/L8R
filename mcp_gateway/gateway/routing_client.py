"""Multi-tenant, multi-device HTTP client with per-request routing.

One ``RoutingClient`` serves all devices of a vendor pack across every tenant.
Every generated tool carries optional ``tenant`` and ``device`` header
parameters; ``send()`` resolves the tenant's registry, then the device within
it, rewrites the request URL (host/port) and swaps the auth headers, then
strips both routing headers before the request reaches the appliance. Without
a ``tenant`` header the optional ``default_tenant`` applies; without a
``device`` header the tenant's primary device applies. An explicit ``device``
that does not resolve is rejected with a synthetic 404 (``unknown_device``) —
it never falls back to the primary.
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


def _strip_blank_query_params(request: httpx.Request) -> None:
    """Drop query parameters whose value is an empty string.

    FastMCP's OpenAPI layer serializes optional query parameters the caller
    left unset as ``name=`` (blank). The Fortinet REST APIs reject blanks:
    enum-constrained filters answer 400 (``Invalid value [] to parameter
    [typeFilter]``) and blank numeric params surface as server-side SQL errors
    (``organizationId=`` -> ``SQLGrammarException``). An absent parameter, by
    contrast, lets the appliance apply its own default. These are read-only
    GETs, so a blank filter and an omitted filter are semantically identical —
    dropping the blank is safe and restores the appliance default path.
    """
    params = request.url.params
    if not params:
        return
    kept = [(k, v) for k, v in params.multi_items() if v != ""]
    if len(kept) == len(params.multi_items()):
        return
    dropped = [k for k, v in params.multi_items() if v == ""]
    request.url = request.url.copy_with(query=str(httpx.QueryParams(kept)).encode("ascii") or None)
    log.debug("Stripped blank query params: %s", ", ".join(sorted(set(dropped))))


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
        (header device — unknown values are rejected with a synthetic 404 —
        else the tenant's primary). Because resolution is
        per-request against the live registry, admin-API hot reloads — including
        primary changes — take effect without rebuilding the client; base_url
        only remains as the no-route fallback (unconfigured.invalid).
        """
        _strip_blank_query_params(request)

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
                # An explicit-but-unknown device must NEVER fall back to the
                # primary: the caller addressed a specific appliance, and a
                # silent redirect executes the whole call chain against the
                # wrong one (cross-device data contamination). Fail loudly.
                log.warning(
                    "Routing: device '%s' not found for tenant '%s'. Rejecting request.",
                    target_device_id,
                    registry.customer_id,
                )
                return httpx.Response(
                    status_code=404,
                    json={
                        "error": "unknown_device",
                        "message": (
                            f"device '{target_device_id}' not found for "
                            f"tenant '{registry.customer_id}'"
                        ),
                    },
                    request=request,
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
