"""Admin REST API for the device inventory.

Mounted as custom HTTP routes on the FastMCP server (no MCP tools are added,
so the tool-name freeze is unaffected). The support_ai_agent platform calls
these endpoints when a user manages devices from the frontend: the gateway
encrypts the token, persists ``devices/managed.yaml`` and hot-reloads the
in-memory registries — appliance tokens never leave this process.

Auth: shared secret in the ``X-Admin-Token`` header, compared against the
``GATEWAY_ADMIN_TOKEN`` environment variable. When the variable is unset every
admin endpoint (except ``/admin/health``) answers 503 — the API is opt-in.

Tenancy: the gateway is multi-tenant (routing resolves the tenant per request).
The API can write any tenant's files. Tenants are provisioned via
``POST /admin/tenants`` (creates ``inventory/tenants/<cid>/`` + tenant.yaml)
and removed via ``DELETE /admin/tenants/{cid}`` (refused while hand-maintained
device files exist). A mutation reloads that tenant's cached routing slice if
present (``"reloaded"`` in the response); an as-yet-uncached tenant is a no-op
here — its next request builds it fresh from disk.
"""

from __future__ import annotations

import logging
import os
import re
import secrets as py_secrets
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from fastmcp import FastMCP

from .config import GatewaySettings, TenantRegistries
from .inventory import (
    DeviceExistsError,
    DeviceNotFoundError,
    EncryptionUnavailableError,
    ManagedInventoryStore,
    ManualDevicesPresentError,
    TenantExistsError,
    TenantNotFoundError,
    UnmanagedDeviceError,
)
from .vendor_pack import AppliancePack

log = logging.getLogger("gateway.admin")

ADMIN_TOKEN_ENV = "GATEWAY_ADMIN_TOKEN"
ADMIN_TOKEN_HEADER = "x-admin-token"
REDACTED = "***"

# Tenant ids become filesystem directory names: keep them to a safe slug.
TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class ConnectionWrite(BaseModel):
    host: str
    port: int = 443
    token: Optional[str] = Field(default=None, description="Plaintext token; write-only")
    verify_ssl: bool = False


class ConnectionPatch(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    token: Optional[str] = None
    verify_ssl: Optional[bool] = None


class DeviceWrite(BaseModel):
    id: str
    name: str
    type: str
    os_version: Optional[str] = Field(
        default=None, description="Firmware/OS version of the device (e.g. '7.4.5')"
    )
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    primary: bool = False
    connection: ConnectionWrite


class DevicePatch(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    os_version: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    primary: Optional[bool] = None
    connection: Optional[ConnectionPatch] = None


class TenantWrite(BaseModel):
    id: str = Field(..., pattern=TENANT_ID_RE.pattern)
    name: str
    description: Optional[str] = None


def _redact(entry: Dict[str, Any], managed: bool) -> Dict[str, Any]:
    """Raw device entry -> API representation with the token redacted."""
    out = dict(entry)
    connection = dict(out.get("connection") or {})
    if "token" in connection:
        connection["token"] = REDACTED
    out["connection"] = connection
    out["managed"] = managed
    return out


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


def register_admin_routes(
    gateway: FastMCP,
    registries: Dict[str, TenantRegistries],
    packs: List[AppliancePack],
    settings: GatewaySettings,
) -> None:
    known_device_types = {pack.manifest.device_type for pack in packs}

    def _check_auth(request: Request) -> Optional[JSONResponse]:
        expected = os.getenv(ADMIN_TOKEN_ENV)
        if not expected:
            return _error(503, "admin_disabled", f"{ADMIN_TOKEN_ENV} is not configured.")
        provided = request.headers.get(ADMIN_TOKEN_HEADER, "")
        if not py_secrets.compare_digest(provided, expected):
            return _error(401, "unauthorized", "Invalid or missing X-Admin-Token header.")
        return None

    def _reload_registries(customer_id: str) -> bool:
        """Reload the tenant's cached routing slice across all device types.

        Multi-tenant: any tenant's mutation refreshes its own registry. A tenant
        not yet cached is a no-op here — its next request builds it fresh from
        disk. Returns whether any cached slice was reloaded (informational).
        """
        reloaded_any = False
        for tenant_registries in registries.values():
            if tenant_registries.reload(customer_id):
                reloaded_any = True
        return reloaded_any

    def _store_error(e: Exception) -> JSONResponse:
        if isinstance(e, DeviceExistsError) or isinstance(e, UnmanagedDeviceError):
            return _error(409, "conflict", str(e))
        if isinstance(e, TenantExistsError):
            return _error(409, "tenant_exists", str(e))
        if isinstance(e, ManualDevicesPresentError):
            return _error(409, "manual_devices_present", str(e))
        if isinstance(e, DeviceNotFoundError):
            return _error(404, "not_found", str(e))
        if isinstance(e, TenantNotFoundError):
            return _error(404, "unknown_tenant", str(e))
        if isinstance(e, EncryptionUnavailableError):
            return _error(503, "encryption_unavailable", str(e))
        log.exception("Unexpected admin API failure")
        return _error(500, "internal_error", str(e))

    def _validation_error(e: ValidationError) -> JSONResponse:
        return JSONResponse({"error": "validation_error", "detail": e.errors()}, status_code=422)

    @gateway.custom_route("/admin/health", methods=["GET"])
    async def admin_health(request: Request) -> JSONResponse:
        return JSONResponse(
            {"status": "ok", "admin_enabled": bool(os.getenv(ADMIN_TOKEN_ENV))}
        )

    @gateway.custom_route("/admin/packs", methods=["GET"])
    async def admin_packs(request: Request) -> JSONResponse:
        denied = _check_auth(request)
        if denied:
            return denied
        return JSONResponse(
            [
                {
                    "vendor": pack.vendor,
                    "appliance": pack.name,
                    "version": pack.version,
                    "display_name": pack.manifest.display_name,
                    "device_type": pack.manifest.device_type,
                    "prefix": pack.prefix,
                    "pack_key": pack.pack_key,
                }
                for pack in packs
            ]
        )

    @gateway.custom_route("/admin/tenants", methods=["POST"])
    async def admin_create_tenant(request: Request) -> JSONResponse:
        denied = _check_auth(request)
        if denied:
            return denied
        try:
            payload = TenantWrite(**(await request.json()))
        except ValidationError as e:
            return _validation_error(e)
        except Exception:
            return _error(400, "bad_request", "Body must be a JSON object.")

        store = ManagedInventoryStore()
        try:
            entry = store.create_tenant(payload.id, payload.name, payload.description)
        except Exception as e:
            return _store_error(e)

        reloaded = _reload_registries(payload.id)
        log.info("Tenant '%s' provisioned via admin API.", payload.id)
        return JSONResponse({"tenant": entry, "reloaded": reloaded}, status_code=201)

    @gateway.custom_route("/admin/tenants/{cid}", methods=["DELETE"])
    async def admin_delete_tenant(request: Request) -> JSONResponse:
        denied = _check_auth(request)
        if denied:
            return denied
        cid = request.path_params["cid"]
        if not TENANT_ID_RE.match(cid):
            return _error(422, "invalid_tenant_id", f"Tenant id '{cid}' is not a valid slug.")

        store = ManagedInventoryStore()
        try:
            store.delete_tenant(cid)
        except Exception as e:
            return _store_error(e)

        reloaded = _reload_registries(cid)
        log.info("Tenant '%s' removed via admin API.", cid)
        return JSONResponse({"deleted": cid, "reloaded": reloaded})

    @gateway.custom_route("/admin/tenants/{cid}/devices", methods=["GET"])
    async def admin_list_devices(request: Request) -> JSONResponse:
        denied = _check_auth(request)
        if denied:
            return denied
        cid = request.path_params["cid"]
        store = ManagedInventoryStore()
        devices = [_redact(e, managed=False) for e in store.list_manual_raw(cid)]
        devices += [_redact(e, managed=True) for e in store.list_raw(cid)]
        return JSONResponse({"customer_id": cid, "devices": devices})

    @gateway.custom_route("/admin/tenants/{cid}/devices", methods=["POST"])
    async def admin_create_device(request: Request) -> JSONResponse:
        denied = _check_auth(request)
        if denied:
            return denied
        cid = request.path_params["cid"]
        store = ManagedInventoryStore()
        if not (store.tenants_dir / cid).is_dir():
            # Creating for an unknown tenant would silently mint a bogus
            # tenant directory (and strand the device there).
            return _error(
                404,
                "unknown_tenant",
                f"Tenant '{cid}' has no inventory directory; "
                f"provision it first via POST /admin/tenants.",
            )
        try:
            payload = DeviceWrite(**(await request.json()))
        except ValidationError as e:
            return _validation_error(e)
        except Exception:
            return _error(400, "bad_request", "Body must be a JSON object.")

        if payload.type not in known_device_types:
            return _error(
                422,
                "unknown_device_type",
                f"Device type '{payload.type}' does not match any appliance pack "
                f"(known: {sorted(known_device_types)}).",
            )

        device = payload.model_dump(exclude_none=True)
        token = device.get("connection", {}).pop("token", None)
        try:
            entry, warnings = store.create(cid, device, plaintext_token=token)
        except Exception as e:
            return _store_error(e)

        reloaded = _reload_registries(cid)
        return JSONResponse(
            {"device": _redact(entry, managed=True), "reloaded": reloaded, "warnings": warnings},
            status_code=201,
        )

    @gateway.custom_route("/admin/tenants/{cid}/devices/{device_id}", methods=["PATCH"])
    async def admin_update_device(request: Request) -> JSONResponse:
        denied = _check_auth(request)
        if denied:
            return denied
        cid = request.path_params["cid"]
        device_id = request.path_params["device_id"]
        try:
            payload = DevicePatch(**(await request.json()))
        except ValidationError as e:
            return _validation_error(e)
        except Exception:
            return _error(400, "bad_request", "Body must be a JSON object.")

        if payload.type is not None and payload.type not in known_device_types:
            return _error(
                422,
                "unknown_device_type",
                f"Device type '{payload.type}' does not match any appliance pack "
                f"(known: {sorted(known_device_types)}).",
            )

        patch = payload.model_dump(exclude_none=True)
        token = patch.get("connection", {}).pop("token", None)
        store = ManagedInventoryStore()
        try:
            entry, warnings = store.update(cid, device_id, patch, plaintext_token=token)
        except Exception as e:
            return _store_error(e)

        reloaded = _reload_registries(cid)
        return JSONResponse(
            {"device": _redact(entry, managed=True), "reloaded": reloaded, "warnings": warnings}
        )

    @gateway.custom_route("/admin/tenants/{cid}/devices/{device_id}", methods=["DELETE"])
    async def admin_delete_device(request: Request) -> JSONResponse:
        denied = _check_auth(request)
        if denied:
            return denied
        cid = request.path_params["cid"]
        device_id = request.path_params["device_id"]
        store = ManagedInventoryStore()
        try:
            store.delete(cid, device_id)
        except Exception as e:
            return _store_error(e)

        reloaded = _reload_registries(cid)
        return JSONResponse({"deleted": device_id, "reloaded": reloaded})

    @gateway.custom_route("/admin/reload", methods=["POST"])
    async def admin_reload(request: Request) -> JSONResponse:
        denied = _check_auth(request)
        if denied:
            return denied
        for tenant_registries in registries.values():
            tenant_registries.reload_all()
        return JSONResponse(
            {
                "reloaded": True,
                "registries": {
                    device_type: tr.cached_tenant_count()
                    for device_type, tr in registries.items()
                },
            }
        )

    log.info("Admin API routes registered (enabled: %s).", bool(os.getenv(ADMIN_TOKEN_ENV)))
