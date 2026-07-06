"""Multi-device HTTP client with per-request routing.

One ``RoutingClient`` serves all devices of a vendor pack. Every generated
tool carries an optional ``device`` header parameter; when present, ``send()``
rewrites the request URL (host/port) and swaps the auth headers for that
device, then strips the header before it reaches the appliance. Without the
header, requests go to the primary device the client was built with.
"""

from __future__ import annotations

import logging
from typing import Dict

import httpx

from .auth import AuthStrategy
from .config import DeviceRegistry, GatewaySettings

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
        registry: DeviceRegistry,
        auth: AuthStrategy,
        settings: GatewaySettings,
    ) -> None:
        self._registry = registry
        self._auth = auth

        conn: Dict[str, object] = registry.resolve_primary_connection()
        host = conn.get("host") or _UNCONFIGURED_HOST
        port = int(conn.get("port", 443))
        verify_ssl = bool(conn.get("verify_ssl", False))

        headers = {"Content-Type": "application/json"}
        headers.update(self._auth.headers(conn))

        super().__init__(
            base_url=f"https://{host}:{port}",
            headers=headers,
            verify=verify_ssl,
            timeout=httpx.Timeout(settings.http_timeout, connect=settings.http_connect_timeout),
            event_hooks={
                "request": [_log_request],
                "response": [_log_response],
            },
        )

    async def send(self, request: httpx.Request, *args, **kwargs) -> httpx.Response:
        """Intercept the final request to apply dynamic device routing.

        Interception happens here (not in build_request) because FastMCP may
        build requests through different paths.
        """
        target_device_id = None

        # The generated 'device' parameter (in: header) lands in request.headers
        if "device" in request.headers:
            target_device_id = request.headers["device"]
            del request.headers["device"]  # Must not reach the appliance
        # Alternate spelling kept for manual usage / future renames
        elif "x-target-device" in request.headers:
            target_device_id = request.headers["x-target-device"]
            del request.headers["x-target-device"]

        if target_device_id:
            device = self._registry.get(target_device_id)
            if device:
                conn = device.connection
                host = conn.get("host")
                port = int(conn.get("port", 443))

                # httpx.URL is immutable; swap scheme/host/port via copy_with
                request.url = request.url.copy_with(scheme="https", host=host, port=port)

                for name, value in self._auth.headers(conn).items():
                    request.headers[name] = value

                log.info("Routing: switched target to device '%s' (host: %s)", target_device_id, host)
            else:
                log.warning(
                    "Routing: device '%s' not found in inventory. Using primary.", target_device_id
                )

        return await super().send(request, *args, **kwargs)
