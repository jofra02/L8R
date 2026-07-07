"""RoutingClient dynamic resolution: primary changes apply after registry.reload().

httpx.AsyncClient.send is patched to capture the final request instead of
hitting the network.
"""

import asyncio

import httpx
import pytest
import yaml

from gateway.auth import get_auth_strategy
from gateway.config import DeviceRegistry, GatewaySettings
from gateway.inventory.manager import get_inventory
from gateway.routing_client import RoutingClient

TENANT = "fake_client"


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
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)
    return captured


def _routed_client(registry: DeviceRegistry) -> RoutingClient:
    return RoutingClient(registry, get_auth_strategy("bearer_header"), GatewaySettings())


def _do_request(client: RoutingClient, headers=None):
    async def run():
        request = client.build_request("GET", "/api/v2/monitor/system/status", headers=headers)
        return await RoutingClient.send(client, request)

    return asyncio.run(run())


def test_unrouted_request_goes_to_primary(inventory_root, capture_send):
    registry = DeviceRegistry(TENANT, "fortios")
    client = _routed_client(registry)
    _do_request(client)
    assert (capture_send["host"], capture_send["port"]) == ("10.0.0.1", 443)
    assert capture_send["auth"] == "Bearer token-a"


def test_device_header_routes_and_is_stripped(inventory_root, capture_send):
    registry = DeviceRegistry(TENANT, "fortios")
    client = _routed_client(registry)
    _do_request(client, headers={"device": "fw_b"})
    assert (capture_send["host"], capture_send["port"]) == ("10.0.0.2", 8443)
    assert capture_send["auth"] == "Bearer token-b"
    assert capture_send["device_header"] is None


def test_unknown_device_falls_back_to_primary(inventory_root, capture_send):
    registry = DeviceRegistry(TENANT, "fortios")
    client = _routed_client(registry)
    _do_request(client, headers={"device": "nope"})
    assert (capture_send["host"], capture_send["port"]) == ("10.0.0.1", 443)
    assert capture_send["auth"] == "Bearer token-a"


def test_primary_change_applies_after_reload_without_rebuild(inventory_root, capture_send):
    registry = DeviceRegistry(TENANT, "fortios")
    client = _routed_client(registry)

    # Swap the primary flag on disk (as the admin API would) and reload
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
    registry = DeviceRegistry(TENANT, "fortios")
    client = _routed_client(registry)
    _do_request(client)
    assert "unconfigured.invalid" in capture_send["url"]
    get_inventory.cache_clear()
