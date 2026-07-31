"""License normalalization: fortigate.license_status / fortiedr.system_summary
/ fortiedr.organizations normalizers, pack v3/v4 + type v2 sync, and the
enrichment paths (hosted-console 403 fallback via list-organizations,
mapping precedence organizations-over-summary).

Fixtures mirror REAL device output (reconquista FGT60E blob shapes).

Run: uv run pytest src/testing/test_assets_licensing.py
"""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from src.assessments.normalizers import get_normalizer
from src.assets.enrichment import engine
from src.assets.registry import (
    KIND_ASSET_TYPE,
    KIND_ENRICHMENT_PACK,
    sync_definitions,
)
from src.core.mcp_executor import MCPToolResult
from src.core.orm import AssetDefinitionVersionORM, AssetORM

EXP = 1761350400  # 2025-10-25T00:00:00+00:00
EXP_ISO = "2025-10-25T00:00:00+00:00"

FGT_LICENSE_RESULTS = {
    "antivirus": {"type": "downloaded_fds_object", "status": "expired", "expires": EXP,
                  "version": "93.04557", "entitlement": "AVDB", "db_status": "db_type_extended",
                  "engine": {"version": "7.00049"}, "last_update": 1752335700},
    "botnet_ip": {"type": "downloaded_fds_object", "status": "licensed", "version": "7.04359"},
    "web_filtering": {"type": "live_fortiguard_service", "status": "expired", "expires": EXP,
                      "entitlement": "FURL"},
    "fortimanager_cloud": {"type": "live_cloud_service", "status": "no_license", "entitlement": "FMGC"},
    "forticloud_sandbox": {"type": "live_cloud_service", "status": "free_license", "expires": EXP},
    "vdom": {"type": "platform", "max": 10, "used": 1, "can_upgrade": False},
    "sms": {"type": "other", "status": "no_license", "max": 0, "used": 0},
    "forticare": {"type": "cloud_service_status", "status": "registered",
                  "registration_status": "registered", "account": "x@example.com",
                  "company": "Fortinet",
                  "support": {"hardware": {"status": "expired", "support_level": "8x5",
                                           "expires": EXP},
                              "enhanced": {}}},
    "forticloud": {"type": "cloud_service_status", "status": "cloud_na"},
    "fortiguard": {"type": "cloud_service_status", "connected": True,
                   "server_address": "173.243.140.6:443",
                   "last_connection_success": 1785417681},
    "ot_detection": {"detect_definitions": {"type": "downloaded_fds_object", "status": "expired",
                                            "expires": EXP, "version": "1.1"},
                     "patch_definitions": {"status": "expired"}},
    "iot_detection": {"type": "live_fortiguard_service", "status": "expired", "expires": EXP,
                      "entitlement": "IOTH",
                      "definitions": {"status": "licensed", "version": "2.2"}},
    "future_widget": {"type": "quantum_service", "status": "mystery"},
    "not_a_dict": "hello",
}


def fgt_payload():
    return json.dumps({"results": FGT_LICENSE_RESULTS, "serial": "FGT60E000000",
                       "version": "v7.4.5", "status": "success"})


# --- fortigate.license_status ---

def test_fortigate_license_status_normalizer():
    out = get_normalizer("fortigate.license_status")(fgt_payload())
    assert out["meta"]["serial"] == "FGT60E000000"
    assert out["results"] == FGT_LICENSE_RESULTS  # raw blob untouched
    by_key = {e["key"]: e for e in out["normalized"]}

    av = by_key["antivirus"]
    assert av["category"] == "signature" and av["state"] == "expired"
    assert av["expires"] == EXP_ISO and av["entitlement"] == "AVDB"
    assert av["version"] == "93.04557"
    assert av["details"]["db_status"] == "db_type_extended"
    assert av["last_update"].startswith("2025-07-12")

    assert by_key["botnet_ip"]["state"] == "ok"
    assert by_key["web_filtering"]["category"] == "cloud_service"
    assert by_key["fortimanager_cloud"]["state"] == "none"
    assert by_key["forticloud_sandbox"]["state"] == "ok"  # free_license
    assert by_key["forticloud"]["state"] == "none"        # cloud_na

    vdom = by_key["vdom"]
    assert vdom["category"] == "platform" and vdom["seats"] == {"used": 1, "max": 10}
    sms = by_key["sms"]
    assert sms["category"] == "capacity" and sms["state"] == "none"

    fc = by_key["forticare"]
    assert fc["category"] == "registration" and fc["state"] == "ok"
    assert fc["details"]["account"] == "x@example.com"
    hw = by_key["forticare.support.hardware"]
    assert hw["category"] == "support_contract" and hw["state"] == "expired"
    assert hw["details"]["support_level"] == "8x5" and hw["expires"] == EXP_ISO
    assert "forticare.support.enhanced" not in by_key  # empty level not emitted

    fg = by_key["fortiguard"]
    assert fg["status"] == "connected" and fg["state"] == "ok"
    assert fg["details"]["server_address"] == "173.243.140.6:443"
    assert fg["details"]["last_connection_success"].startswith("2026-07-30")

    # nested containers flatten; parent without own body emits no entry
    assert "ot_detection" not in by_key
    assert by_key["ot_detection.detect_definitions"]["category"] == "signature"
    assert by_key["ot_detection.patch_definitions"]["state"] == "expired"
    # iot_detection has its own body AND nested definitions
    assert by_key["iot_detection"]["state"] == "expired"
    assert by_key["iot_detection.definitions"]["state"] == "ok"

    # unknown shapes are preserved, never dropped
    assert by_key["future_widget"]["state"] == "unknown"
    assert "not_a_dict" not in by_key


def test_fortigate_license_status_defensive():
    out = get_normalizer("fortigate.license_status")("not json {{{")
    assert "error" in out
    out = get_normalizer("fortigate.license_status")(json.dumps({"results": []}))
    assert out["normalized"] == []


# --- fortiedr normalizers ---

FEDR_SUMMARY = {
    "licenseType": "Discover, Protect and Response",
    "licenseExpirationDate": "2027-03-01 00:00:00",
    "licenseFeatures": ["Threat Hunting", "Forensics"],
    "workstationCollectorsLicenseCapacity": 100,
    "workstationsCollectorsInUse": 7,
    "serverCollectorsLicenseCapacity": 20,
    "serverCollectorsInUse": 3,
    "iotDevicesLicenseCapacity": 0,
    "iotDevicesInUse": 0,
    "registeredCollectors": 10,
    "serialNumber": "FEDR-001",
    "managementVersion": "6.2.1",
    "managementHostname": "edr.example.com",
    "customerName": "Acme",
}


def test_fortiedr_system_summary_normalizer():
    # hosted-console envelope variant
    out = get_normalizer("fortiedr.system_summary")(json.dumps({"result": FEDR_SUMMARY}))
    assert out["results"]["serialNumber"] == "FEDR-001"  # generic mappings intact
    by_key = {e["key"]: e for e in out["normalized"]}
    lic = by_key["console_license"]
    assert lic["category"] == "platform" and lic["state"] == "ok"
    assert lic["expires"] == "2027-03-01T00:00:00"
    assert lic["details"]["license_type"].startswith("Discover")
    assert lic["details"]["features"] == ["Threat Hunting", "Forensics"]
    assert by_key["workstations"]["seats"] == {"used": 7, "max": 100}
    assert by_key["servers"]["seats"] == {"used": 3, "max": 20}
    assert out["capacity"]["workstations"] == {"used": 7, "max": 100}
    assert out["capacity"]["registered_collectors"] == 10


FEDR_ORGS = [
    {"name": "Druidics", "organizationId": 1, "serialNumber": "S1",
     "expirationDate": "2026-12-01 00:00:00", "isAdminAccount": False,
     "workstationsAllocated": 50, "workstationsInUse": 7,
     "serversAllocated": 10, "serversInUse": 3,
     "edr": True, "forensics": False},
    {"name": "Other", "organizationId": 2,
     "expirationDate": "2026-09-15 00:00:00",
     "workstationsAllocated": 5, "workstationsInUse": 1},
]


def test_fortiedr_organizations_normalizer():
    out = get_normalizer("fortiedr.organizations")(json.dumps(FEDR_ORGS))
    by_key = {e["key"]: e for e in out["normalized"]}
    org = by_key["org:Druidics"]
    assert org["category"] == "platform" and org["state"] == "ok"
    assert org["expires"] == "2026-12-01T00:00:00"
    assert org["details"]["features"] == {"edr": True, "forensics": False}
    assert by_key["org:Druidics/workstations"]["seats"] == {"used": 7, "max": 50}
    assert by_key["org:Other/workstations"]["seats"] == {"used": 1, "max": 5}
    # earliest expiry across orgs
    assert out["expiration"] == "2026-09-15T00:00:00"
    # aggregated capacity
    assert out["capacity"]["workstations"] == {"used": 8, "max": 55}
    assert out["capacity"]["servers"] == {"used": 3, "max": 10}

    # single-object payload (org-scoped consoles may return one dict)
    single = get_normalizer("fortiedr.organizations")(json.dumps(FEDR_ORGS[1]))
    assert "org:Other" in {e["key"] for e in single["normalized"]}


DASH_STATUS = {"licenseType": "Predict-Protect-and-Response",
               "expirationDate": "31-Dec-2026",
               "numberOfDaysRemaining": 89, "usedStorage": 0.98}
DASH_CAPACITY = {"result": [{"name": "endpoints", "inUse": 4, "remaining": 21}]}


def test_fortiedr_dashboard_normalizers():
    """Real hosted-console payloads (verified live against Druidics)."""
    st = get_normalizer("fortiedr.license_status_dashboard")(json.dumps(DASH_STATUS))
    lic = st["normalized"][0]
    assert lic["key"] == "console_license" and lic["state"] == "ok"
    assert lic["expires"] == "2026-12-31T00:00:00+00:00"  # "%d-%b-%Y" format
    assert lic["details"]["license_type"] == "Predict-Protect-and-Response"
    assert lic["details"]["days_remaining"] == 89

    cap = get_normalizer("fortiedr.license_capacity_dashboard")(json.dumps(DASH_CAPACITY))
    assert cap["capacity"] == {"endpoints": {"used": 4, "max": 25}}

    # empty/malformed payloads stay defensive
    assert get_normalizer("fortiedr.license_status_dashboard")(json.dumps({}))["normalized"] == []
    assert get_normalizer("fortiedr.license_capacity_dashboard")(json.dumps({"result": []}))["capacity"] == {}


# --- pack/type version sync ---

async def test_definitions_sync_versions(asset_session_factory):
    async with asset_session_factory() as s:
        await sync_definitions(s)
        rows = (await s.execute(select(AssetDefinitionVersionORM))).scalars().all()
        latest = {}
        for r in rows:
            key = (r.kind, r.definition_id)
            latest[key] = max(latest.get(key, 0), r.version)
        assert latest[(KIND_ENRICHMENT_PACK, "fortigate")] == 3
        assert latest[(KIND_ENRICHMENT_PACK, "fortiedr")] == 5
        assert latest[(KIND_ASSET_TYPE, "firewall")] == 2
        assert latest[(KIND_ASSET_TYPE, "edr_console")] == 2


# --- enrichment paths (stubbed tools) ---

@pytest.fixture()
async def env(asset_session_factory, monkeypatch):
    async with asset_session_factory() as s:
        await sync_definitions(s)
    monkeypatch.setattr(engine, "async_session_factory", asset_session_factory)
    tasks = []
    orig_create_task = asyncio.create_task

    def capture(coro, **kw):
        t = orig_create_task(coro, **kw)
        tasks.append(t)
        return t

    monkeypatch.setattr(engine.asyncio, "create_task", capture)
    return asset_session_factory, tasks


async def make_asset(factory, *, asset_type, device_type, name="DEV") -> str:
    asset_id = uuid.uuid4().hex
    async with factory() as s:
        s.add(AssetORM(
            id=asset_id, customer_id="t1", name=name,
            ref=f"{asset_type}-{asset_id[:6]}", asset_type=asset_type, managed=True,
            mcp_config={"vendor": "fortinet", "appliance": asset_type,
                        "device_type": device_type, "host": "h", "port": 443},
            attributes={}, provenance={}, tags=[],
        ))
        await s.commit()
    return asset_id


def stub_tools(monkeypatch, responses):
    async def execute(tool_name, args, customer_id, *, enforce_read_only=False, timeout_s=None):
        result = responses.get(tool_name, {})
        if isinstance(result, MCPToolResult):
            return result
        return MCPToolResult(ok=True, content=json.dumps(result))

    monkeypatch.setattr(engine, "execute_mcp_tool", execute)


async def run_enrichment(env_tuple, asset_id) -> None:
    factory, tasks = env_tuple
    await engine.enqueue_enrichment("t1", asset_id, trigger="manual")
    for t in list(tasks):
        await t
    tasks.clear()


async def get_attrs(factory, asset_id):
    async with factory() as s:
        asset = (await s.execute(
            select(AssetORM).where(AssetORM.id == asset_id))).scalar_one()
        return dict(asset.attributes or {}), dict(asset.provenance or {})


SUMMARY_TOOL = "fedr62_mgmt_administrator_get_admin_list_system_summary"
ORGS_TOOL = "fedr62_mgmt_organizations_get_list"
COLLECTORS_TOOL = "fedr62_mgmt_system_inventory_get_list_collectors"
DASH_STATUS_TOOL = "fedr62_mgmt_dashboard_get_license_status_per_organization"
DASH_CAP_TOOL = "fedr62_mgmt_dashboard_get_license_capacity_per_organization"
FGT_LICENSE_TOOL = "fgt74_monitor_lic_get_license_status"

FORBIDDEN = MCPToolResult(ok=False, error="403 forbidden", error_type="authorization")


async def test_fortigate_enrichment_writes_licenses(env, monkeypatch):
    factory, _ = env
    asset_id = await make_asset(factory, asset_type="firewall", device_type="fortios")
    stub_tools(monkeypatch, {
        "fgt74_monitor_sys_get_status": {"results": {"hostname": "fw", "model": "FGT60E"},
                                         "serial": "FGT60E000000", "version": "v7.4.5"},
        FGT_LICENSE_TOOL: json.loads(fgt_payload()),
    })
    await run_enrichment(env, asset_id)
    attrs, prov = await get_attrs(factory, asset_id)
    assert isinstance(attrs.get("licenses"), list) and len(attrs["licenses"]) > 10
    assert attrs["license_status"] == FGT_LICENSE_RESULTS  # raw blob kept
    assert prov["attributes.licenses"]["source"] == "discovered"
    states = {e["key"]: e["state"] for e in attrs["licenses"]}
    assert states["antivirus"] == "expired"


async def test_fortiedr_dashboard_only_hosted_console(env, monkeypatch):
    """The real Druidics scenario: admin/* AND organizations 403, dashboard
    license endpoints are the only reachable source."""
    factory, _ = env
    asset_id = await make_asset(factory, asset_type="edr_console", device_type="fortiedr")
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: FORBIDDEN,
        ORGS_TOOL: FORBIDDEN,
        DASH_STATUS_TOOL: DASH_STATUS,
        DASH_CAP_TOOL: DASH_CAPACITY,
        COLLECTORS_TOOL: [],
    })
    await run_enrichment(env, asset_id)
    attrs, prov = await get_attrs(factory, asset_id)
    keys = {e["key"] for e in attrs["licenses"]}
    assert keys == {"console_license"}
    assert attrs["license_type"] == "Predict-Protect-and-Response"
    assert attrs["license_expiration"] == "2026-12-31T00:00:00+00:00"
    assert attrs["license_capacity"] == {"endpoints": {"used": 4, "max": 25}}
    assert prov["attributes.licenses"]["source"] == "discovered"


async def test_fortiedr_summary_overrides_dashboard(env, monkeypatch):
    """Admin console: dashboard baseline applies first, summary (richer)
    overwrites licenses/type/capacity."""
    factory, _ = env
    asset_id = await make_asset(factory, asset_type="edr_console", device_type="fortiedr")
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: {"result": FEDR_SUMMARY},
        ORGS_TOOL: FORBIDDEN,
        DASH_STATUS_TOOL: DASH_STATUS,
        DASH_CAP_TOOL: DASH_CAPACITY,
        COLLECTORS_TOOL: [],
    })
    await run_enrichment(env, asset_id)
    attrs, _ = await get_attrs(factory, asset_id)
    keys = {e["key"] for e in attrs["licenses"]}
    assert "workstations" in keys  # summary's richer list won
    assert attrs["license_type"].startswith("Discover")
    assert attrs["license_capacity"]["workstations"] == {"used": 7, "max": 100}


async def test_fortiedr_hosted_403_falls_back_to_organizations(env, monkeypatch):
    factory, _ = env
    asset_id = await make_asset(factory, asset_type="edr_console", device_type="fortiedr")
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: MCPToolResult(ok=False, error="403 forbidden",
                                    error_type="authorization"),
        ORGS_TOOL: {"result": FEDR_ORGS[:1]},
        COLLECTORS_TOOL: [],
    })
    await run_enrichment(env, asset_id)
    attrs, _ = await get_attrs(factory, asset_id)
    keys = {e["key"] for e in attrs["licenses"]}
    assert "org:Druidics" in keys
    assert attrs["license_expiration"] == "2026-12-01T00:00:00"
    assert attrs["license_capacity"]["workstations"] == {"used": 7, "max": 50}
    assert "license_type" not in attrs  # summary never ran


async def test_fortiedr_orgs_win_but_summary_keeps_type(env, monkeypatch):
    factory, _ = env
    asset_id = await make_asset(factory, asset_type="edr_console", device_type="fortiedr")
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: {"result": FEDR_SUMMARY},
        ORGS_TOOL: FEDR_ORGS[:1],
        COLLECTORS_TOOL: [],
    })
    await run_enrichment(env, asset_id)
    attrs, _ = await get_attrs(factory, asset_id)
    keys = {e["key"] for e in attrs["licenses"]}
    assert "org:Druidics" in keys and "console_license" not in keys  # orgs win
    assert attrs["license_type"].startswith("Discover")              # summary scalar kept
    assert attrs["license_features"] == ["Threat Hunting", "Forensics"]
    # organizations expiration overwrites summary's
    assert attrs["license_expiration"] == "2026-12-01T00:00:00"


async def test_fortiedr_orgs_failure_degrades_to_summary(env, monkeypatch):
    factory, _ = env
    asset_id = await make_asset(factory, asset_type="edr_console", device_type="fortiedr")
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: {"result": FEDR_SUMMARY},
        ORGS_TOOL: MCPToolResult(ok=False, error="boom", error_type="unknown"),
        COLLECTORS_TOOL: [],
    })
    await run_enrichment(env, asset_id)
    attrs, _ = await get_attrs(factory, asset_id)
    keys = {e["key"] for e in attrs["licenses"]}
    assert "console_license" in keys
    assert attrs["license_capacity"]["workstations"] == {"used": 7, "max": 100}
