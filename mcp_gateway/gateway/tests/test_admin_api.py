"""Admin API tests: auth, device CRUD on managed.yaml, hot reload.

Uses a temporary inventory tree (via the INVENTORY_ROOT env override) and a
minimal FastMCP instance with only the admin routes registered — the full
spec pipeline is exercised separately by test_name_freeze.py.
"""

import yaml
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from fastmcp import FastMCP

from gateway.admin_api import register_admin_routes
from gateway.config import GatewaySettings, TenantRegistries
from gateway.inventory.manager import get_inventory
from gateway.vendor_pack import ApplianceManifest, AppliancePack

TENANT = "fake_client"
ADMIN_TOKEN = "test-admin-token"
AUTH = {"X-Admin-Token": ADMIN_TOKEN}


@pytest.fixture()
def inventory_root(tmp_path, monkeypatch):
    """Temp inventory with one hand-maintained fortios device."""
    devices_dir = tmp_path / "tenants" / TENANT / "devices"
    devices_dir.mkdir(parents=True)
    (devices_dir / "firewalls.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "fw_manual",
                    "name": "Manual FW",
                    "type": "fortios",
                    "primary": True,
                    "connection": {"host": "10.0.0.1", "port": 443, "token": "plain-token"},
                }
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("INVENTORY_ROOT", str(tmp_path))
    monkeypatch.setenv("INVENTORY_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("GATEWAY_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("ACTIVE_CUSTOMER_ID", TENANT)
    get_inventory.cache_clear()
    yield tmp_path
    get_inventory.cache_clear()


def _make_pack(tmp_path: Path) -> AppliancePack:
    manifest = ApplianceManifest(
        vendor="fortinet",
        name="fortigate",
        version="7.4",
        display_name="FortiGate Suite",
        prefix="fgt74",
        device_type="fortios",
    )
    return AppliancePack(manifest, tmp_path / "pack")


@pytest.fixture()
def client_and_registry(inventory_root):
    # TENANT is the default tenant (ACTIVE_CUSTOMER_ID set by inventory_root).
    # Prime its slice so hot-reload tests can inspect the same DeviceRegistry the
    # admin API reloads in place.
    tenant_registries = TenantRegistries("fortios", default_tenant=TENANT)
    registry = tenant_registries.get(TENANT)
    gateway = FastMCP("test-gateway")
    register_admin_routes(
        gateway, {"fortios": tenant_registries}, [_make_pack(inventory_root)], GatewaySettings()
    )
    app = gateway.http_app(path="/sse/", transport="sse")
    with TestClient(app) as client:
        yield client, registry


def _managed_path(root: Path) -> Path:
    return root / "tenants" / TENANT / "devices" / "managed.yaml"


def _device_payload(device_id="fw_branch", **overrides):
    payload = {
        "id": device_id,
        "name": "Branch FW",
        "type": "fortios",
        "connection": {"host": "10.0.2.1", "port": 8443, "token": "s3cret", "verify_ssl": False},
    }
    payload.update(overrides)
    return payload


def test_health_reports_enabled(client_and_registry):
    client, _ = client_and_registry
    resp = client.get("/admin/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "admin_enabled": True}


def test_auth_missing_env_disables_api(client_and_registry, monkeypatch):
    client, _ = client_and_registry
    monkeypatch.delenv("GATEWAY_ADMIN_TOKEN")
    resp = client.get(f"/admin/tenants/{TENANT}/devices", headers=AUTH)
    assert resp.status_code == 503


def test_auth_wrong_token_rejected(client_and_registry):
    client, _ = client_and_registry
    resp = client.get(f"/admin/tenants/{TENANT}/devices", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401
    resp = client.get(f"/admin/tenants/{TENANT}/devices")
    assert resp.status_code == 401


def test_create_device_persists_encrypted_and_reloads(client_and_registry, inventory_root):
    client, registry = client_and_registry
    resp = client.post(f"/admin/tenants/{TENANT}/devices", headers=AUTH, json=_device_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["reloaded"] is True
    assert body["device"]["connection"]["token"] == "***"

    raw = _managed_path(inventory_root).read_text(encoding="utf-8")
    assert "s3cret" not in raw
    entries = yaml.safe_load(raw)
    assert entries[0]["id"] == "fw_branch"
    assert entries[0]["connection"]["token"].startswith("ENC(")

    # Hot reload: the registry sees the new device without a restart
    assert "fw_branch" in registry.devices
    assert registry.devices["fw_branch"].connection["token"] == "s3cret"  # decrypted in memory


def test_create_duplicate_or_manual_id_conflicts(client_and_registry):
    client, _ = client_and_registry
    assert (
        client.post(
            f"/admin/tenants/{TENANT}/devices", headers=AUTH, json=_device_payload("fw_manual")
        ).status_code
        == 409
    )
    client.post(f"/admin/tenants/{TENANT}/devices", headers=AUTH, json=_device_payload())
    assert (
        client.post(f"/admin/tenants/{TENANT}/devices", headers=AUTH, json=_device_payload()).status_code
        == 409
    )


def test_create_unknown_device_type_rejected(client_and_registry):
    client, _ = client_and_registry
    resp = client.post(
        f"/admin/tenants/{TENANT}/devices", headers=AUTH, json=_device_payload(type="cisco_ios")
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "unknown_device_type"


def test_list_redacts_tokens_and_flags_managed(client_and_registry):
    client, _ = client_and_registry
    client.post(f"/admin/tenants/{TENANT}/devices", headers=AUTH, json=_device_payload())
    resp = client.get(f"/admin/tenants/{TENANT}/devices", headers=AUTH)
    assert resp.status_code == 200
    devices = {d["id"]: d for d in resp.json()["devices"]}
    assert devices["fw_manual"]["managed"] is False
    assert devices["fw_branch"]["managed"] is True
    assert all(d["connection"]["token"] == "***" for d in devices.values())


def test_patch_without_token_preserves_ciphertext(client_and_registry, inventory_root):
    client, registry = client_and_registry
    client.post(f"/admin/tenants/{TENANT}/devices", headers=AUTH, json=_device_payload())
    original = yaml.safe_load(_managed_path(inventory_root).read_text(encoding="utf-8"))
    original_enc = original[0]["connection"]["token"]

    resp = client.patch(
        f"/admin/tenants/{TENANT}/devices/fw_branch",
        headers=AUTH,
        json={"connection": {"host": "10.0.9.9"}},
    )
    assert resp.status_code == 200, resp.text
    updated = yaml.safe_load(_managed_path(inventory_root).read_text(encoding="utf-8"))
    assert updated[0]["connection"]["token"] == original_enc  # byte-identical ENC string
    assert updated[0]["connection"]["host"] == "10.0.9.9"
    assert registry.devices["fw_branch"].connection["host"] == "10.0.9.9"


def test_packs_endpoint_reports_versioned_identity(client_and_registry):
    client, _ = client_and_registry
    resp = client.get("/admin/packs", headers=AUTH)
    assert resp.status_code == 200
    packs = resp.json()
    assert packs == [
        {
            "vendor": "fortinet",
            "appliance": "fortigate",
            "version": "7.4",
            "display_name": "FortiGate Suite",
            "device_type": "fortios",
            "prefix": "fgt74",
            "pack_key": "fortinet/fortigate/7.4",
        }
    ]


def test_os_version_round_trips_create_patch_get(client_and_registry, inventory_root):
    client, registry = client_and_registry
    resp = client.post(
        f"/admin/tenants/{TENANT}/devices",
        headers=AUTH,
        json=_device_payload(os_version="7.4.5"),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["device"]["os_version"] == "7.4.5"

    entries = yaml.safe_load(_managed_path(inventory_root).read_text(encoding="utf-8"))
    assert entries[0]["os_version"] == "7.4.5"
    assert registry.devices["fw_branch"].os_version == "7.4.5"

    resp = client.patch(
        f"/admin/tenants/{TENANT}/devices/fw_branch",
        headers=AUTH,
        json={"os_version": "7.4.7"},
    )
    assert resp.status_code == 200, resp.text
    entries = yaml.safe_load(_managed_path(inventory_root).read_text(encoding="utf-8"))
    assert entries[0]["os_version"] == "7.4.7"
    assert registry.devices["fw_branch"].os_version == "7.4.7"

    listed = client.get(f"/admin/tenants/{TENANT}/devices", headers=AUTH).json()
    managed = [d for d in listed["devices"] if d["id"] == "fw_branch"]
    assert managed[0]["os_version"] == "7.4.7"


def test_mutating_unmanaged_device_conflicts(client_and_registry):
    client, _ = client_and_registry
    resp = client.patch(
        f"/admin/tenants/{TENANT}/devices/fw_manual", headers=AUTH, json={"name": "x"}
    )
    assert resp.status_code == 409
    assert client.delete(f"/admin/tenants/{TENANT}/devices/fw_manual", headers=AUTH).status_code == 409


def test_delete_device_removes_from_file_and_registry(client_and_registry, inventory_root):
    client, registry = client_and_registry
    client.post(f"/admin/tenants/{TENANT}/devices", headers=AUTH, json=_device_payload())
    assert "fw_branch" in registry.devices

    resp = client.delete(f"/admin/tenants/{TENANT}/devices/fw_branch", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["reloaded"] is True
    entries = yaml.safe_load(_managed_path(inventory_root).read_text(encoding="utf-8"))
    assert entries == []
    assert "fw_branch" not in registry.devices

    assert client.delete(f"/admin/tenants/{TENANT}/devices/fw_branch", headers=AUTH).status_code == 404


def test_primary_uniqueness_and_manual_primary_warning(client_and_registry, inventory_root):
    client, _ = client_and_registry
    client.post(
        f"/admin/tenants/{TENANT}/devices", headers=AUTH, json=_device_payload("fw_a", primary=True)
    )
    resp = client.post(
        f"/admin/tenants/{TENANT}/devices", headers=AUTH, json=_device_payload("fw_b", primary=True)
    )
    assert resp.status_code == 201
    # Manual fw_manual is primary too -> explicit warning
    assert resp.json()["warnings"], "expected a manual-primary warning"

    entries = yaml.safe_load(_managed_path(inventory_root).read_text(encoding="utf-8"))
    primaries = [e["id"] for e in entries if e.get("primary")]
    assert primaries == ["fw_b"]


def test_unknown_tenant_create_rejected(client_and_registry, inventory_root):
    client, _ = client_and_registry
    resp = client.post("/admin/tenants/other_tenant/devices", headers=AUTH, json=_device_payload())
    assert resp.status_code == 404
    assert resp.json()["error"] == "unknown_tenant"
    assert not (inventory_root / "tenants" / "other_tenant").exists()


def test_known_other_tenant_writes_files_but_does_not_reload(client_and_registry, inventory_root):
    client, registry = client_and_registry
    (inventory_root / "tenants" / "other_tenant").mkdir(parents=True)
    before = set(registry.devices)
    resp = client.post("/admin/tenants/other_tenant/devices", headers=AUTH, json=_device_payload())
    assert resp.status_code == 201
    assert resp.json()["reloaded"] is False
    assert set(registry.devices) == before
    other = inventory_root / "tenants" / "other_tenant" / "devices" / "managed.yaml"
    assert other.exists()


def test_create_tenant_provisions_files(client_and_registry, inventory_root):
    client, _ = client_and_registry
    resp = client.post(
        "/admin/tenants", headers=AUTH, json={"id": "acme", "name": "Acme Corp", "description": "d"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["reloaded"] is False  # not the active tenant
    assert body["tenant"]["id"] == "acme"

    tenant_yaml = inventory_root / "tenants" / "acme" / "tenant.yaml"
    assert tenant_yaml.exists()
    data = yaml.safe_load(tenant_yaml.read_text(encoding="utf-8"))
    assert data == {
        "id": "acme",
        "name": "Acme Corp",
        "context": {"critical_networks": [], "contacts": []},
        "description": "d",
    }
    assert (inventory_root / "tenants" / "acme" / "devices").is_dir()

    # Device create no longer answers unknown_tenant for the new tenant
    resp = client.post("/admin/tenants/acme/devices", headers=AUTH, json=_device_payload())
    assert resp.status_code == 201, resp.text


def test_create_tenant_duplicate_conflicts(client_and_registry):
    client, _ = client_and_registry
    assert client.post("/admin/tenants", headers=AUTH, json={"id": "acme", "name": "A"}).status_code == 201
    resp = client.post("/admin/tenants", headers=AUTH, json={"id": "acme", "name": "A"})
    assert resp.status_code == 409
    assert resp.json()["error"] == "tenant_exists"
    # The pre-seeded tenant (bare fixture dir has device files but no tenant.yaml
    # is not the case here: fake_client has devices/, tenant.yaml absent -> adopted)
    resp = client.post("/admin/tenants", headers=AUTH, json={"id": TENANT, "name": "FC"})
    assert resp.status_code == 201  # bare dir adoption


def test_create_tenant_invalid_id_rejected(client_and_registry, inventory_root):
    client, _ = client_and_registry
    resp = client.post("/admin/tenants", headers=AUTH, json={"id": "../evil", "name": "x"})
    assert resp.status_code == 422
    assert not (inventory_root / "evil").exists()
    assert not (inventory_root / "tenants" / ".." / "evil").exists()
    assert client.post("/admin/tenants", headers=AUTH, json={"name": "x"}).status_code == 422


def test_create_tenant_requires_auth(client_and_registry):
    client, _ = client_and_registry
    resp = client.post("/admin/tenants", headers={"X-Admin-Token": "wrong"}, json={"id": "a", "name": "a"})
    assert resp.status_code == 401


def test_delete_tenant_removes_tree(client_and_registry, inventory_root):
    client, _ = client_and_registry
    client.post("/admin/tenants", headers=AUTH, json={"id": "acme", "name": "Acme"})
    client.post("/admin/tenants/acme/devices", headers=AUTH, json=_device_payload())
    # Example files never block deletion
    (inventory_root / "tenants" / "acme" / "devices" / "fw.example.yaml").write_text(
        "[]", encoding="utf-8"
    )

    resp = client.delete("/admin/tenants/acme", headers=AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": "acme", "reloaded": False}
    assert not (inventory_root / "tenants" / "acme").exists()

    assert client.delete("/admin/tenants/acme", headers=AUTH).status_code == 404


def test_delete_tenant_with_manual_devices_conflicts(client_and_registry, inventory_root):
    client, _ = client_and_registry
    resp = client.delete(f"/admin/tenants/{TENANT}", headers=AUTH)
    assert resp.status_code == 409
    assert resp.json()["error"] == "manual_devices_present"
    assert "firewalls.yaml" in resp.json()["message"]
    assert (inventory_root / "tenants" / TENANT / "devices" / "firewalls.yaml").exists()


def test_delete_active_tenant_reloads_empty(client_and_registry, inventory_root):
    client, registry = client_and_registry
    (inventory_root / "tenants" / TENANT / "devices" / "firewalls.yaml").unlink()
    client.post(f"/admin/tenants/{TENANT}/devices", headers=AUTH, json=_device_payload())
    registry.reload()
    assert registry.devices

    resp = client.delete(f"/admin/tenants/{TENANT}", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["reloaded"] is True
    assert registry.devices == {}


def test_delete_tenant_invalid_id_rejected(client_and_registry):
    client, _ = client_and_registry
    resp = client.delete("/admin/tenants/%2E%2E", headers=AUTH)
    assert resp.status_code in (404, 422)  # router or slug validation, never a deletion
    resp = client.delete("/admin/tenants/bad.id", headers=AUTH)
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_tenant_id"


def test_reload_endpoint(client_and_registry, inventory_root):
    client, registry = client_and_registry
    # Simulate out-of-band edit
    extra = _device_payload("fw_oob")
    extra["connection"].pop("token")
    managed = _managed_path(inventory_root)
    managed.parent.mkdir(parents=True, exist_ok=True)
    managed.write_text(yaml.safe_dump([extra]), encoding="utf-8")

    resp = client.post("/admin/reload", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["reloaded"] is True
    assert "fw_oob" in registry.devices
