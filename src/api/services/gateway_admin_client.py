"""HTTP client for the MCP gateway inventory admin API.

Propagates managed-device changes (create/update/delete) to the gateway,
which encrypts tokens and persists its own YAML inventory. Sync failures are
never raised into the request path: every call returns a ``GatewaySyncResult``
so the local inventory write always succeeds and the error is surfaced to the
caller/UI instead.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel, Field

from src.config import settings

logger = logging.getLogger(__name__)

ADMIN_TOKEN_HEADER = "X-Admin-Token"


class GatewaySyncResult(BaseModel):
    status: Literal["synced", "error", "skipped"]
    reloaded: Optional[bool] = None
    error: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class GatewayAdminClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_settings(cls) -> Optional["GatewayAdminClient"]:
        """Client from app settings, or None when sync is not configured."""
        if not settings.MCP_GATEWAY_ADMIN_URL or not settings.MCP_GATEWAY_ADMIN_TOKEN:
            return None
        return cls(
            base_url=settings.MCP_GATEWAY_ADMIN_URL,
            token=settings.MCP_GATEWAY_ADMIN_TOKEN,
            timeout=settings.MCP_GATEWAY_ADMIN_TIMEOUT,
        )

    async def _request(self, method: str, path: str, json: Optional[dict] = None) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers={ADMIN_TOKEN_HEADER: self.token},
            )

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            return body.get("message") or body.get("detail") or response.text
        except Exception:
            return response.text or f"HTTP {response.status_code}"

    def _result_from_response(self, response: httpx.Response) -> GatewaySyncResult:
        if response.status_code >= 400:
            return GatewaySyncResult(
                status="error",
                error=f"HTTP {response.status_code}: {self._error_detail(response)}",
            )
        try:
            body: Dict[str, Any] = response.json()
        except Exception:
            body = {}
        return GatewaySyncResult(
            status="synced",
            reloaded=body.get("reloaded"),
            warnings=body.get("warnings") or [],
        )

    async def upsert_device(
        self, customer_id: str, payload: Dict[str, Any], *, create: bool
    ) -> GatewaySyncResult:
        device_id = payload.get("id")
        try:
            if create:
                response = await self._request(
                    "POST", f"/admin/tenants/{customer_id}/devices", json=payload
                )
                # Idempotent retry after a previously failed local/gateway sync:
                # the device may already exist in the gateway.
                if response.status_code == 409:
                    patch = {k: v for k, v in payload.items() if k != "id"}
                    response = await self._request(
                        "PATCH", f"/admin/tenants/{customer_id}/devices/{device_id}", json=patch
                    )
            else:
                patch = {k: v for k, v in payload.items() if k != "id"}
                response = await self._request(
                    "PATCH", f"/admin/tenants/{customer_id}/devices/{device_id}", json=patch
                )
                # Device missing in the gateway (drift or first-time enable on
                # an existing component): fall back to create.
                if response.status_code == 404:
                    response = await self._request(
                        "POST", f"/admin/tenants/{customer_id}/devices", json=payload
                    )
            return self._result_from_response(response)
        except Exception as e:
            logger.warning(f"Gateway inventory sync failed for device '{device_id}': {e}")
            return GatewaySyncResult(status="error", error=str(e))

    async def create_tenant(
        self, customer_id: str, name: str, description: Optional[str] = None
    ) -> GatewaySyncResult:
        payload: Dict[str, Any] = {"id": customer_id, "name": name}
        if description:
            payload["description"] = description
        try:
            response = await self._request("POST", "/admin/tenants", json=payload)
            # Already provisioned (retry after a failed sync, or out-of-band
            # provisioning): goal state reached.
            if response.status_code == 409:
                return GatewaySyncResult(status="synced")
            return self._result_from_response(response)
        except Exception as e:
            logger.warning(f"Gateway tenant provisioning failed for '{customer_id}': {e}")
            return GatewaySyncResult(status="error", error=str(e))

    async def delete_tenant(self, customer_id: str) -> GatewaySyncResult:
        try:
            response = await self._request("DELETE", f"/admin/tenants/{customer_id}")
            # Already absent in the gateway: treat as success (goal state reached)
            if response.status_code == 404:
                return GatewaySyncResult(status="synced")
            # 409 manual_devices_present stays an error: operator action required
            return self._result_from_response(response)
        except Exception as e:
            logger.warning(f"Gateway tenant delete failed for '{customer_id}': {e}")
            return GatewaySyncResult(status="error", error=str(e))

    async def delete_device(self, customer_id: str, device_id: str) -> GatewaySyncResult:
        try:
            response = await self._request(
                "DELETE", f"/admin/tenants/{customer_id}/devices/{device_id}"
            )
            # Already absent in the gateway: treat as success (goal state reached)
            if response.status_code == 404:
                return GatewaySyncResult(status="synced")
            return self._result_from_response(response)
        except Exception as e:
            logger.warning(f"Gateway inventory delete failed for device '{device_id}': {e}")
            return GatewaySyncResult(status="error", error=str(e))
