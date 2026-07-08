"""RoutingClient dynamic resolution: primary changes apply after registry.reload().

httpx.AsyncClient.send is patched to capture the final request instead of
hitting the network.
"""

import asyncio

import httpx
import pytest
import yaml

from gateway.auth import get_auth_strategy
from gateway.config import GatewaySettings, TenantRegistries
from gateway.inventory.manager import get_inventory
from gateway.routing_client import RoutingClient

TENANT = "fake_client"
TENANT_B = "other_client"


@pytest.fixture()
def inventory_root(tmp_path, monkeypatch):
    devices_dir = tmp_path / "tenants" / TENANT / "devices"
    devices_dir.mkdir(parents=True)
    (devices_dir / "firewalls.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "fw_a",
                    "name": "FW A",
                    "type": "fortios",
                    "primary": True,
                    "connection": {"host": "10.0.0.1", "port": 443, "token": "token-a"},
                },
                {
                    "id": "fw_b",
                    "name": "FW B",
                    "type": "fortios",
                    "connection": {"host": "10.0.0.2", "port": 8443, "token": "token-b"},
                },
            ]
        ),
        encoding="utf-8",
    )
    # A second tenant with a colliding device id 'fw_a' but a different host,
    # to prove per-request tenant scoping (no cross-tenant leak).
    devices_dir_b = tmp_path / "tenants" / TENANT_B / "devices"
    devices_dir_b.mkdir(parents=True)
    (devices_dir_b / "firewalls.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "fw_a",
                    "name": "FW A (tenant B)",
                    "type": "fortios",
                    "primary": True,
                    "connection": {"host": "172.16.0.1", "port": 9443, "token": "token-b-a"},
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("INVENTORY_ROOT", str(tmp_path))
    monkeypatch.delenv("INVENTORY_MASTER_KEY", raising=False)
    get_inventory.cache_clear()
    yield tmp_path
    get_inventory.cache_clear()


@pytest.fixture()
def capture_send(monkeypatch):
    captured = {}

    async def fake_send(self, request, *args, **kwargs):
        captured["url"] = str(request.url)
        captured["host"] = request.url.host
        # request.url.port is None when it matches the scheme default (443)
        captured["port"] = request.url.port or 443
        captured["auth"] = request.headers.get("authorization")
        captured["device_header"] = request.headers.get("device")
        captured["tenant_header"] = request.headers.get("tenant")
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)
    return captured


def _routed_client(default_tenant=None) -> RoutingClient:
    registries = TenantRegistries("fortios", default_tenant=default_tenant)
    return RoutingClient(registries, get_auth_strategy("bearer_header"), GatewaySettings())


def _do_request(client: RoutingClient, headers=None):
    async def run():
        request = client.build_request("GET", "/api/v2/monitor/system/status", headers=headers)
        return await RoutingClient.send(client, request)

    return asyncio.run(run())


def test_unrouted_request_goes_to_default_tenant_primary(inventory_root, capture_send):
    client = _routed_client(default_tenant=TENANT)
    _do_request(client)
    assert (capture_send["host"], capture_send["port"]) == ("10.0.0.1", 443)
    assert capture_send["auth"] == "Bearer token-a"


def test_device_header_routes_and_is_stripped(inventory_root, capture_send):
    client = _routed_client(default_tenant=TENANT)
    _do_request(client, headers={"device": "fw_b"})
    assert (capture_send["host"], capture_send["port"]) == ("10.0.0.2", 8443)
    assert capture_send["auth"] == "Bearer token-b"
    assert capture_send["device_header"] is None


def test_unknown_device_falls_back_to_primary(inventory_root, capture_send):
    client = _routed_client(default_tenant=TENANT)
    _do_request(client, headers={"device": "nope"})
    assert (capture_send["host"], capture_send["port"]) == ("10.0.0.1", 443)
    assert capture_send["auth"] == "Bearer token-a"


def test_tenant_header_selects_inventory_and_is_stripped(inventory_root, capture_send):
    # No default: tenant must come from the header. TENANT_B has its own 'fw_a'.
    client = _routed_client()
    _do_request(client, headers={"tenant": TENANT_B})
    assert (capture_send["host"], capture_send["port"]) == ("172.16.0.1", 9443)
    assert capture_send["auth"] == "Bearer token-b-a"
    assert capture_send["tenant_header"] is None


def test_same_device_id_routes_per_tenant(inventory_root, capture_send):
    # 'fw_a' exists in both tenants with different hosts; the tenant header decides.
    client = _routed_client(default_tenant=TENANT)
    _do_request(client, headers={"tenant": TENANT, "device": "fw_a"})
    assert capture_send["host"] == "10.0.0.1"
    _do_request(client, headers={"tenant": TENANT_B, "device": "fw_a"})
    assert capture_send["host"] == "172.16.0.1"


def test_no_tenant_and_no_default_is_unrouted(inventory_root, capture_send):
    client = _routed_client()  # no default_tenant
    _do_request(client)
    assert "unconfigured.invalid" in capture_send["url"]


def test_primary_change_applies_after_reload_without_rebuild(inventory_root, capture_send):
    client = _routed_client(default_tenant=TENANT)
    # Prime the tenant's registry, then swap the primary flag on disk and reload.
    _do_request(client)
    registry = client._registries.get(TENANT)

    devices_file = inventory_root / "tenants" / TENANT / "devices" / "firewalls.yaml"
    data = yaml.safe_load(devices_file.read_text(encoding="utf-8"))
    data[0]["primary"] = False
    data[1]["primary"] = True
    devices_file.write_text(yaml.safe_dump(data), encoding="utf-8")
    registry.reload()

    _do_request(client)
    assert (capture_send["host"], capture_send["port"]) == ("10.0.0.2", 8443)
    assert capture_send["auth"] == "Bearer token-b"


def test_empty_registry_keeps_unconfigured_fallback(tmp_path, monkeypatch, capture_send):
    monkeypatch.setenv("INVENTORY_ROOT", str(tmp_path))
    get_inventory.cache_clear()
    client = _routed_client(default_tenant=TENANT)  # tenant dir absent -> empty
    _do_request(client)
    assert "unconfigured.invalid" in capture_send["url"]
    get_inventory.cache_clear()
