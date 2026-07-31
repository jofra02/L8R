"""Nested subitems: pack DAG validation, engine parent resolution, scoped
absence, partial-unique identity, subitem detail/ancestors/children API.

The shipped fortiedr pack stays root-only; nesting is exercised through a
pinned synthetic version 99 adding a `nic` rule parented to `endpoint`
(declared BEFORE the endpoint rule on purpose — the engine must topo-sort).

Run: uv run pytest src/testing/test_assets_subitems_nesting.py
"""

import asyncio
import copy
import json
import uuid

import pytest
from sqlalchemy import func, select, text

from src.api.exceptions import APIError
from src.assets.enrichment import engine
from src.assets.registry import (
    KIND_ENRICHMENT_PACK,
    PACKS_DIR,
    content_hash,
    load_pack_file,
    sync_definitions,
)
from src.assets.schema import EnrichmentPackDefinition
from src.assets.service import AssetService
from src.core.mcp_executor import MCPToolResult
from src.core.orm import AssetDefinitionVersionORM, AssetORM, AssetSubitemORM

SUMMARY_TOOL = "fedr62_mgmt_administrator_get_admin_list_system_summary"
COLLECTORS_TOOL = "fedr62_mgmt_system_inventory_get_list_collectors"

SUMMARY = {"managementVersion": "6.2.1", "serialNumber": "FEDR-001"}

NIC_RULE = {
    "step": "collectors",
    "items": "results[*]",
    "kind": "nic",
    "identity": {"source": "fortiedr", "external_id": "macAddresses[0]"},
    "name": "name",
    "parent": {"kind": "endpoint", "external_id": "parentId"},
}


def collector(id_, name, mac, parent_id=None, state="Running"):
    return {
        "id": id_, "name": name, "state": state,
        "macAddresses": [mac] if mac else [],
        "parentId": parent_id if parent_id is not None else id_,
    }


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


def nested_pack_raw() -> dict:
    raw = load_pack_file(PACKS_DIR / "fortiedr.yaml").model_dump(mode="json")
    raw["version"] = 99
    # Child rule first: resolution must not depend on declaration order.
    # Deep copy — the validation tests mutate the rule in place.
    raw["subitems"] = [copy.deepcopy(NIC_RULE)] + raw["subitems"]
    return raw


async def pin_nested_pack(factory) -> None:
    pack = EnrichmentPackDefinition.model_validate(nested_pack_raw())
    async with factory() as s:
        s.add(AssetDefinitionVersionORM(
            id=uuid.uuid4().hex, kind=KIND_ENRICHMENT_PACK,
            definition_id=pack.pack_id, version=pack.version,
            label=pack.label, content=pack.model_dump(mode="json"),
            content_hash=content_hash(pack),
        ))
        await s.commit()


async def make_console(factory, customer_id="t1") -> str:
    asset_id = uuid.uuid4().hex
    async with factory() as s:
        s.add(AssetORM(
            id=asset_id, customer_id=customer_id, name="EDR Console",
            ref=f"edr-{asset_id[:6]}", asset_type="edr_console", managed=True,
            mcp_config={"vendor": "fortinet", "appliance": "fortiedr",
                        "device_type": "fortiedr", "host": "edr", "port": 443},
            attributes={}, provenance={}, tags=[],
        ))
        await s.commit()
    return asset_id


def stub_tools(monkeypatch, responses):
    async def execute(tool_name, args, customer_id, *, enforce_read_only=False, timeout_s=None):
        result = responses[tool_name]
        if callable(result):
            result = result(args)
        if isinstance(result, MCPToolResult):
            return result
        return MCPToolResult(ok=True, content=json.dumps(result))

    monkeypatch.setattr(engine, "execute_mcp_tool", execute)


async def run_enrichment(env_tuple, asset_id) -> str:
    factory, tasks = env_tuple
    run_id = await engine.enqueue_enrichment("t1", asset_id, trigger="manual")
    for t in list(tasks):
        await t
    tasks.clear()
    return run_id


async def get_run(factory, run_id):
    from src.core.orm import AssetSyncRunORM
    async with factory() as s:
        return (await s.execute(
            select(AssetSyncRunORM).where(AssetSyncRunORM.id == run_id)
        )).scalar_one()


async def subitems_of(factory, asset_id):
    async with factory() as s:
        return (await s.execute(
            select(AssetSubitemORM).where(AssetSubitemORM.parent_asset_id == asset_id)
        )).scalars().all()


# --- pack validation ---

def test_pack_rejects_unknown_parent_kind():
    raw = nested_pack_raw()
    raw["subitems"][0]["parent"]["kind"] = "ghost"
    with pytest.raises(ValueError, match="parent kind 'ghost'"):
        EnrichmentPackDefinition.model_validate(raw)


def test_pack_rejects_self_parent():
    raw = nested_pack_raw()
    raw["subitems"][0]["parent"]["kind"] = "nic"
    with pytest.raises(ValueError, match="references itself"):
        EnrichmentPackDefinition.model_validate(raw)


def test_pack_rejects_parent_cycle():
    raw = nested_pack_raw()
    # endpoint -> nic while nic -> endpoint
    raw["subitems"][1]["parent"] = {"kind": "nic", "external_id": "id"}
    with pytest.raises(ValueError, match="cycle"):
        EnrichmentPackDefinition.model_validate(raw)


# --- engine ---

async def test_nested_run_links_children(env, monkeypatch):
    factory, _ = env
    await pin_nested_pack(factory)
    asset_id = await make_console(factory)
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: SUMMARY,
        COLLECTORS_TOOL: [collector(11, "PC-A", "mac-a"), collector(12, "PC-B", "mac-b")],
    })
    run_id = await run_enrichment(env, asset_id)
    run = await get_run(factory, run_id)
    assert run.status in ("completed", "completed_with_errors")
    assert run.stats["subitems_created"] == 4

    rows = await subitems_of(factory, asset_id)
    endpoints = {r.external_id: r for r in rows if r.kind == "endpoint"}
    nics = {r.external_id: r for r in rows if r.kind == "nic"}
    assert set(endpoints) == {"11", "12"} and set(nics) == {"mac-a", "mac-b"}
    assert all(e.parent_subitem_id is None for e in endpoints.values())
    assert nics["mac-a"].parent_subitem_id == endpoints["11"].id
    assert nics["mac-b"].parent_subitem_id == endpoints["12"].id


async def test_nested_rerun_idempotent(env, monkeypatch):
    factory, _ = env
    await pin_nested_pack(factory)
    asset_id = await make_console(factory)
    data = [collector(11, "PC-A", "mac-a")]
    stub_tools(monkeypatch, {SUMMARY_TOOL: SUMMARY, COLLECTORS_TOOL: data})
    await run_enrichment(env, asset_id)
    second = await get_run(factory, await run_enrichment(env, asset_id))
    assert second.stats["subitems_created"] == 0
    assert second.stats["subitems_absent"] == 0
    assert len(await subitems_of(factory, asset_id)) == 2


async def test_unresolved_parent_skipped_never_orphaned_at_root(env, monkeypatch):
    factory, _ = env
    await pin_nested_pack(factory)
    asset_id = await make_console(factory)
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: SUMMARY,
        COLLECTORS_TOOL: [collector(11, "PC-A", "mac-a"),
                          collector(13, "PC-ORPHAN", "mac-c", parent_id=999)],
    })
    run_id = await run_enrichment(env, asset_id)
    run = await get_run(factory, run_id)
    assert any("not found in this run" in w for w in run.stats["warnings"])

    rows = await subitems_of(factory, asset_id)
    nics = [r for r in rows if r.kind == "nic"]
    assert [n.external_id for n in nics] == ["mac-a"]
    assert all(n.parent_subitem_id is not None for n in nics)


async def test_shared_child_identity_across_parents(env, monkeypatch):
    """Two parents may each own a child with the same (source, kind,
    external_id) — identity is unique per hierarchy level, not global."""
    factory, _ = env
    await pin_nested_pack(factory)
    asset_id = await make_console(factory)
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: SUMMARY,
        COLLECTORS_TOOL: [collector(11, "PC-A", "shared-mac"),
                          collector(12, "PC-B", "shared-mac")],
    })
    await run_enrichment(env, asset_id)
    rows = await subitems_of(factory, asset_id)
    nics = [r for r in rows if r.kind == "nic"]
    assert len(nics) == 2
    assert {n.parent_subitem_id for n in nics} == {
        r.id for r in rows if r.kind == "endpoint"
    }


async def test_absence_scoped_to_seen_parents(env, monkeypatch):
    factory, _ = env
    await pin_nested_pack(factory)
    asset_id = await make_console(factory)

    stub_tools(monkeypatch, {
        SUMMARY_TOOL: SUMMARY,
        COLLECTORS_TOOL: [collector(11, "PC-A", "mac-a"), collector(12, "PC-B", "mac-b")],
    })
    await run_enrichment(env, asset_id)

    # PC-A returns without its nic -> nic marked absent under that parent;
    # PC-B untouched.
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: SUMMARY,
        COLLECTORS_TOOL: [collector(11, "PC-A", None), collector(12, "PC-B", "mac-b")],
    })
    run = await get_run(factory, await run_enrichment(env, asset_id))
    assert run.stats["subitems_absent"] == 1
    rows = {(r.kind, r.external_id): r for r in await subitems_of(factory, asset_id)}
    assert rows[("nic", "mac-a")].absent is True
    assert rows[("nic", "mac-b")].absent is False
    assert rows[("endpoint", "11")].absent is False

    # A scan that drops PC-A entirely sweeps the endpoint (root scope) but
    # leaves its children alone — their parent was not seen this run.
    stub_tools(monkeypatch, {
        SUMMARY_TOOL: SUMMARY,
        COLLECTORS_TOOL: [collector(12, "PC-B", "mac-b")],
    })
    await run_enrichment(env, asset_id)
    rows = {(r.kind, r.external_id): r for r in await subitems_of(factory, asset_id)}
    assert rows[("endpoint", "11")].absent is True
    assert rows[("nic", "mac-a")].absent is True  # unchanged from previous run
    assert rows[("nic", "mac-b")].absent is False


# --- identity indexes (sqlite enforces the partial unique indexes too) ---

async def test_duplicate_root_identity_rejected(asset_session_factory):
    async with asset_session_factory() as s:
        await sync_definitions(s)
        parent = uuid.uuid4().hex
        s.add(AssetORM(id=parent, customer_id="t1", name="A", ref="a1",
                       asset_type="edr_console", attributes={}, provenance={}, tags=[]))
        await s.commit()
        for _ in range(2):
            s.add(AssetSubitemORM(
                id=uuid.uuid4().hex, customer_id="t1", parent_asset_id=parent,
                source="fortiedr", kind="endpoint", external_id="dup",
                name="X", attributes={},
            ))
        with pytest.raises(Exception, match="(?i)unique|integrity"):
            await s.commit()


# --- service: detail, ancestors, children, filters ---

async def seed_chain(factory):
    """console asset -> ep (endpoint) -> nic -> vlan; plus sibling ep2."""
    asset_id = await make_console(factory)
    ids = {"asset": asset_id}
    async with factory() as s:
        def add(key, kind, name, parent_key=None, **kw):
            row_id = uuid.uuid4().hex
            ids[key] = row_id
            s.add(AssetSubitemORM(
                id=row_id, customer_id="t1", parent_asset_id=asset_id,
                parent_subitem_id=ids.get(parent_key) if parent_key else None,
                source="fortiedr", kind=kind, external_id=key, name=name,
                attributes={}, **kw,
            ))
        add("ep", "endpoint", "DC1", state="Running")
        add("ep2", "endpoint", "WS2", state="Disconnected", absent=True)
        add("nic", "nic", "eth0", parent_key="ep", state="Up")
        add("vlan", "vlan", "vlan10", parent_key="nic")
        await s.commit()
    return ids


async def test_get_subitem_detail_and_ancestors(env):
    factory, _ = env
    ids = await seed_chain(factory)
    async with factory() as s:
        svc = AssetService(s)
        row = await svc.get_subitem("t1", ids["asset"], ids["vlan"])
        chain = await svc.subitem_ancestors(row)
        assert [c["id"] for c in chain] == [ids["ep"], ids["nic"]]
        assert [c["kind"] for c in chain] == ["endpoint", "nic"]

        with pytest.raises(APIError) as e:
            await svc.get_subitem("t2", ids["asset"], ids["vlan"])
        assert e.value.status_code == 404

        other_asset = await make_console(factory)
        with pytest.raises(APIError) as e:
            await svc.get_subitem("t1", other_asset, ids["vlan"])
        assert e.value.status_code == 404


async def test_list_subitems_hierarchy_scoping_and_counts(env):
    factory, _ = env
    ids = await seed_chain(factory)
    async with factory() as s:
        svc = AssetService(s)

        rows, total = await svc.list_subitems(
            "t1", ids["asset"], filters={"parent_subitem_id": "root"},
            page=1, page_size=10)
        assert total == 2 and {r.external_id for r in rows} == {"ep", "ep2"}

        rows, total = await svc.list_subitems(
            "t1", ids["asset"], filters={"parent_subitem_id": ids["ep"]},
            page=1, page_size=10)
        assert total == 1 and rows[0].external_id == "nic"

        _, total = await svc.list_subitems("t1", ids["asset"], page=1, page_size=10)
        assert total == 4  # omitted -> all levels

        counts = await svc.subitem_children_counts([ids["ep"], ids["ep2"], ids["nic"]])
        assert counts == {ids["ep"]: 1, ids["nic"]: 1}


async def test_list_subitems_multi_filters_and_sort(env):
    factory, _ = env
    ids = await seed_chain(factory)
    async with factory() as s:
        svc = AssetService(s)

        _, total = await svc.list_subitems(
            "t1", ids["asset"], filters={"kind": "endpoint,nic"},
            page=1, page_size=10)
        assert total == 3

        rows, total = await svc.list_subitems(
            "t1", ids["asset"], filters={"name": "dc,eth"},
            page=1, page_size=10)
        assert total == 2 and {r.name for r in rows} == {"DC1", "eth0"}

        _, total = await svc.list_subitems(
            "t1", ids["asset"],
            filters={"kind": "endpoint", "state": "Running"},
            page=1, page_size=10)
        assert total == 1

        _, total = await svc.list_subitems(
            "t1", ids["asset"], filters={"absent": False, "kind": "endpoint"},
            page=1, page_size=10)
        assert total == 1

        rows, _ = await svc.list_subitems(
            "t1", ids["asset"], sort="-name", page=1, page_size=10)
        assert [r.name for r in rows] == ["vlan10", "eth0", "WS2", "DC1"]

        with pytest.raises(APIError) as e:
            await svc.list_subitems("t1", ids["asset"], sort="bogus",
                                    page=1, page_size=10)
        assert e.value.status_code == 422


async def test_asset_delete_cascades_subtree(env):
    factory, _ = env
    ids = await seed_chain(factory)
    async with factory() as s:
        await s.execute(text("PRAGMA foreign_keys=ON"))
        asset = (await s.execute(
            select(AssetORM).where(AssetORM.id == ids["asset"])
        )).scalar_one()
        await s.delete(asset)
        await s.commit()
        remaining = (await s.execute(
            select(func.count()).select_from(
                select(AssetSubitemORM).where(
                    AssetSubitemORM.parent_asset_id == ids["asset"]).subquery())
        )).scalar()
        assert remaining == 0
