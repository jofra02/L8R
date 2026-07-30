"""Deterministic enrichment engine tests (sqlite, mocked execute_mcp_tool).

Covers: enqueue preconditions, state machine, pagination, self-enrichment
mappings with manual_wins/discovered_wins + provenance, child asset upsert
idempotency (run twice -> zero duplicates), relation creation, required vs
optional step failures, the startup sweeper and the scheduler tick.

Run: uv run pytest src/testing/test_assets_enrichment.py
"""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import func, select

from src.api.exceptions import APIError
from src.assets.enrichment import engine, scheduler
from src.assets.registry import sync_definitions
from src.core.mcp_executor import MCPToolResult
from src.core.orm import AssetORM, AssetRelationORM, AssetSyncRunORM

SUMMARY_TOOL = "fedr62_mgmt_administrator_get_admin_list_system_summary"
COLLECTORS_TOOL = "fedr62_mgmt_system_inventory_get_list_collectors"

SUMMARY = {
    "managementVersion": "6.2.1",
    "managementHostname": "edr.example.com",
    "serialNumber": "FEDR-001",
    "licenseType": "enterprise",
    "licenseExpirationDate": 1785325353000,
}

COLLECTORS = [
    {"id": 11, "name": "PC-ALPHA", "ipAddress": "10.0.0.11", "operatingSystem": "Windows 11",
     "osFamily": "Windows", "state": "Running", "version": "6.2.0",
     "collectorGroupName": "Default", "macAddresses": ["aa:bb:cc:00:00:11"],
     "loggedUsers": ["alice"], "lastSeenTime": 1785325353000},
    {"id": 12, "name": "PC-BETA", "ipAddress": "10.0.0.12", "operatingSystem": "Ubuntu 24.04",
     "osFamily": "Linux", "state": "Degraded", "version": "6.2.0",
     "collectorGroupName": "Servers", "macAddresses": ["aa:bb:cc:00:00:12"],
     "loggedUsers": [], "lastSeenTime": 1785325353000},
    {"name": "NO-ID", "ipAddress": "10.0.0.13", "macAddresses": []},  # skipped: no identity
]


@pytest.fixture()
async def env(asset_session_factory, monkeypatch):
    """Session factory wired into the engine + captured background tasks."""
    async with asset_session_factory() as s:
        await sync_definitions(s)

    monkeypatch.setattr(engine, "async_session_factory", asset_session_factory)
    monkeypatch.setattr(scheduler, "async_session_factory", asset_session_factory)

    tasks = []
    orig_create_task = asyncio.create_task

    def capture(coro, **kw):
        t = orig_create_task(coro, **kw)
        tasks.append(t)
        return t

    monkeypatch.setattr(engine.asyncio, "create_task", capture)
    return asset_session_factory, tasks


async def make_console(factory, *, managed=True, device_type="fortiedr", **overrides) -> str:
    asset_id = uuid.uuid4().hex
    async with factory() as s:
        s.add(AssetORM(
            id=asset_id, customer_id="t1", name="EDR Console",
            ref=overrides.pop("ref", f"edr-console-{asset_id[:6]}"),
            asset_type="edr_console", managed=managed,
            mcp_config={"vendor": "fortinet", "appliance": "fortiedr",
                        "device_type": device_type, "host": "edr", "port": 443},
            attributes={}, provenance={}, tags=[], **overrides,
        ))
        await s.commit()
    return asset_id


def stub_tools(monkeypatch, responses):
    calls = []

    async def execute(tool_name, args, customer_id, *, enforce_read_only=False, timeout_s=None):
        calls.append({"tool": tool_name, "args": dict(args), "customer_id": customer_id,
                      "enforce_read_only": enforce_read_only})
        result = responses[tool_name]
        if callable(result):
            result = result(args)
        if isinstance(result, MCPToolResult):
            return result
        return MCPToolResult(ok=True, content=json.dumps(result))

    monkeypatch.setattr(engine, "execute_mcp_tool", execute)
    return calls


async def run_enrichment(env_tuple, asset_id, trigger="manual") -> str:
    factory, tasks = env_tuple
    run_id = await engine.enqueue_enrichment("t1", asset_id, trigger=trigger)
    for t in list(tasks):
        await t
    tasks.clear()
    return run_id


async def get_run(factory, run_id):
    async with factory() as s:
        return (await s.execute(
            select(AssetSyncRunORM).where(AssetSyncRunORM.id == run_id)
        )).scalar_one()


# --- enqueue preconditions ---

async def test_enqueue_requires_managed_and_pack(env):
    factory, _ = env
    unmanaged = await make_console(factory, managed=False)
    with pytest.raises(APIError) as e:
        await engine.enqueue_enrichment("t1", unmanaged, trigger="manual")
    assert e.value.status_code == 422

    no_pack = await make_console(factory, device_type="toaster")
    with pytest.raises(APIError) as e:
        await engine.enqueue_enrichment("t1", no_pack, trigger="manual")
    assert "No enrichment pack" in e.value.detail


async def test_enqueue_rejects_concurrent_run(env):
    factory, tasks = env
    asset_id = await make_console(factory)
    async with factory() as s:
        s.add(AssetSyncRunORM(id="r1", customer_id="t1", asset_id=asset_id,
                              pack_id="fortiedr", pack_version=1,
                              status="running", trigger="manual"))
        await s.commit()
    with pytest.raises(APIError) as e:
        await engine.enqueue_enrichment("t1", asset_id, trigger="manual")
    assert e.value.status_code == 409


# --- full run ---

async def test_full_run_children_and_mappings(env, monkeypatch):
    factory, _ = env
    asset_id = await make_console(factory, ref="edr-console")
    calls = stub_tools(monkeypatch, {SUMMARY_TOOL: SUMMARY, COLLECTORS_TOOL: COLLECTORS})

    run_id = await run_enrichment(env, asset_id)
    run = await get_run(factory, run_id)
    assert run.status in ("completed", "completed_with_errors")
    assert run.stats["assets_created"] == 2  # NO-ID item skipped

    # tenant + device routing injected deterministically
    assert all(c["enforce_read_only"] for c in calls)
    assert all(c["args"]["device"] == "edr-console" for c in calls)

    async with factory() as s:
        console = (await s.execute(
            select(AssetORM).where(AssetORM.id == asset_id)
        )).scalar_one()
        assert console.serial_number == "FEDR-001"
        assert console.fqdn == "edr.example.com"
        assert console.attributes["management_version"] == "6.2.1"
        assert console.attributes["license_expiration"].startswith("2026-")
        assert console.provenance["serial_number"]["source"] == "discovered"

        children = (await s.execute(
            select(AssetORM).where(AssetORM.external_source == "fortiedr")
        )).scalars().all()
        assert {c.external_id for c in children} == {"11", "12"}
        alpha = next(c for c in children if c.external_id == "11")
        assert alpha.asset_type == "endpoint"
        assert alpha.ip_address == "10.0.0.11"
        assert alpha.attributes["os"] == "Windows 11"
        assert alpha.attributes["mac"] == "aa:bb:cc:00:00:11"

        relations = (await s.execute(
            select(AssetRelationORM).where(AssetRelationORM.target_asset_id == asset_id)
        )).scalars().all()
        assert len(relations) == 2
        assert all(r.relation_type == "managed_by" and r.provenance == "discovered"
                   for r in relations)


async def test_enveloped_responses_unwrapped(env, monkeypatch):
    """Hosted consoles wrap bodies in {"result": ...} — items must still resolve."""
    factory, _ = env
    asset_id = await make_console(factory)
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: {"result": SUMMARY},
        COLLECTORS_TOOL: {"result": COLLECTORS},
    })
    run_id = await run_enrichment(env, asset_id)
    run = await get_run(factory, run_id)
    assert run.status in ("completed", "completed_with_errors")
    assert run.stats["assets_created"] == 2

    async with factory() as s:
        console = (await s.execute(
            select(AssetORM).where(AssetORM.id == asset_id))).scalar_one()
        assert console.serial_number == "FEDR-001"


async def test_rerun_is_idempotent(env, monkeypatch):
    factory, _ = env
    asset_id = await make_console(factory)
    stub_tools(monkeypatch, {SUMMARY_TOOL: SUMMARY, COLLECTORS_TOOL: COLLECTORS})

    await run_enrichment(env, asset_id)
    await run_enrichment(env, asset_id)

    async with factory() as s:
        n_children = (await s.execute(
            select(func.count()).select_from(
                select(AssetORM).where(AssetORM.external_source == "fortiedr").subquery()
            )
        )).scalar()
        assert n_children == 2, "re-run must not duplicate children"
        n_rel = (await s.execute(
            select(func.count()).select_from(
                select(AssetRelationORM).where(
                    AssetRelationORM.target_asset_id == asset_id).subquery()
            )
        )).scalar()
        assert n_rel == 2


async def test_manual_wins_policy(env, monkeypatch):
    factory, _ = env
    asset_id = await make_console(factory)
    # fqdn mapping policy is manual_wins: a manually set fqdn survives
    async with factory() as s:
        console = (await s.execute(
            select(AssetORM).where(AssetORM.id == asset_id))).scalar_one()
        console.fqdn = "manual.example.com"
        console.provenance = {"fqdn": {"source": "manual"}}
        await s.commit()

    stub_tools(monkeypatch, {SUMMARY_TOOL: SUMMARY, COLLECTORS_TOOL: COLLECTORS})
    await run_enrichment(env, asset_id)

    async with factory() as s:
        console = (await s.execute(
            select(AssetORM).where(AssetORM.id == asset_id))).scalar_one()
        assert console.fqdn == "manual.example.com", "manual_wins violated"
        # discovered_wins target still updated
        assert console.serial_number == "FEDR-001"


async def test_required_step_failure_fails_run(env, monkeypatch):
    # The shipped fortiedr pack has no required steps (v2: hosted consoles
    # 403 on admin/*), so pin a synthetic latest version with summary
    # required to exercise the engine's required-step semantics.
    from src.assets.registry import (
        KIND_ENRICHMENT_PACK, PACKS_DIR, content_hash, load_pack_file,
    )
    from src.assets.schema import EnrichmentPackDefinition
    from src.core.orm import AssetDefinitionVersionORM

    factory, _ = env
    raw = load_pack_file(PACKS_DIR / "fortiedr.yaml").model_dump(mode="json")
    raw["version"] = 99
    raw["steps"][0]["required"] = True
    strict = EnrichmentPackDefinition.model_validate(raw)
    async with factory() as s:
        s.add(AssetDefinitionVersionORM(
            id=uuid.uuid4().hex, kind=KIND_ENRICHMENT_PACK,
            definition_id=strict.pack_id, version=strict.version,
            label=strict.label, content=strict.model_dump(mode="json"),
            content_hash=content_hash(strict),
        ))
        await s.commit()

    asset_id = await make_console(factory)
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: MCPToolResult(ok=False, error="401 unauthorized",
                                    error_type="authorization"),
        COLLECTORS_TOOL: COLLECTORS,
    })
    run_id = await run_enrichment(env, asset_id)
    run = await get_run(factory, run_id)
    assert run.status == "failed"
    assert "summary" in (run.error or "")


async def test_optional_step_failure_completes_with_errors(env, monkeypatch):
    factory, _ = env
    asset_id = await make_console(factory)
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: SUMMARY,
        COLLECTORS_TOOL: MCPToolResult(ok=False, error="boom", error_type="unknown"),
    })
    run_id = await run_enrichment(env, asset_id)
    run = await get_run(factory, run_id)
    assert run.status == "completed_with_errors"
    assert run.stats["steps_failed"] == 1


async def test_pagination(env, monkeypatch):
    factory, _ = env
    asset_id = await make_console(factory)
    page_size = 200  # pinned in the pack definition

    def collectors_page(args):
        page = args.get("pageNumber", 0)
        if page == 0:
            return [{"id": i, "name": f"PC-{i}", "macAddresses": [f"m{i}"]}
                    for i in range(page_size)]
        return [{"id": 9999, "name": "PC-LAST", "macAddresses": ["mz"]}]

    stub_tools(monkeypatch, {SUMMARY_TOOL: SUMMARY, COLLECTORS_TOOL: collectors_page})
    run_id = await run_enrichment(env, asset_id)
    run = await get_run(factory, run_id)
    assert run.stats["assets_created"] == page_size + 1


# --- sweeper / scheduler ---

async def test_sweep_stale_runs(env, monkeypatch):
    factory, _ = env
    asset_id = await make_console(factory)
    async with factory() as s:
        s.add(AssetSyncRunORM(id="stale", customer_id="t1", asset_id=asset_id,
                              pack_id="fortiedr", pack_version=1,
                              status="running", trigger="manual"))
        await s.commit()
    swept = await engine.sweep_stale_sync_runs()
    assert swept == 1
    run = await get_run(factory, "stale")
    assert run.status == "failed" and "restart" in run.error


async def test_scheduler_tick_queues_due_assets(env, monkeypatch):
    factory, _ = env
    due = await make_console(factory)
    fresh = await make_console(factory)
    async with factory() as s:
        # fresh asset has a recent completed run -> not due
        from datetime import datetime, timezone
        s.add(AssetSyncRunORM(id="recent", customer_id="t1", asset_id=fresh,
                              pack_id="fortiedr", pack_version=1,
                              status="completed", trigger="manual",
                              finished_at=datetime.now(timezone.utc)))
        # due asset also blocked? no — its last run is old/none
        await s.commit()

    queued = []

    async def fake_enqueue(customer_id, asset_id, *, trigger):
        queued.append((customer_id, asset_id, trigger))
        return "run-x"

    monkeypatch.setattr(scheduler, "enqueue_enrichment", fake_enqueue)
    n = await scheduler.tick()
    assert n == 1
    assert queued == [("t1", due, "scheduled")]


async def test_scheduler_skips_active_runs(env, monkeypatch):
    factory, _ = env
    asset_id = await make_console(factory)
    async with factory() as s:
        s.add(AssetSyncRunORM(id="act", customer_id="t1", asset_id=asset_id,
                              pack_id="fortiedr", pack_version=1,
                              status="running", trigger="manual"))
        await s.commit()

    async def fail_enqueue(*a, **k):
        raise AssertionError("must not enqueue while a run is active")

    monkeypatch.setattr(scheduler, "enqueue_enrichment", fail_enqueue)
    assert await scheduler.tick() == 0
