"""Context adapter tests: ClientContext assembled from asset tables keeps
the exact pre-migration Pydantic shape for its five consumers.

Run: uv run pytest src/testing/test_context_adapter.py
"""

from datetime import datetime, timezone

from src.assets.context_adapter import (
    asset_to_component_dict,
    assemble_inventory,
)
from src.core.context_store import ContextStore
from src.core.models import ClientContext, Component
from src.core.orm import AssetORM, AssetRelationORM, AssetSubitemORM, ClientContextORM


def make_asset(**kw) -> AssetORM:
    defaults = dict(
        id="fw1", customer_id="t1", name="Branch FW", ref="fw_branch",
        asset_type="firewall", manufacturer="fortinet", criticality="critical",
        attributes={"legacy_role": "firewall", "site": "HQ"},
        provenance={"attributes.site": {"source": "manual"}},
        tags=[], managed=False,
    )
    defaults.update(kw)
    return AssetORM(**defaults)


def test_component_shape_and_legacy_role_roundtrip():
    comp = asset_to_component_dict(make_asset())
    # exact legacy Component shape — validates against the Literal
    model = Component(**comp)
    assert model.id == "fw1"
    assert model.ref == "fw_branch"
    assert model.role == "firewall"
    assert model.vendor == "fortinet"
    assert model.priority == 1  # critical -> 1
    assert model.metadata == {"site": "HQ"}  # legacy_role stripped, provenance hidden


def test_role_fallback_when_no_legacy_role():
    comp = asset_to_component_dict(make_asset(attributes={}, asset_type="edr_console"))
    assert comp["role"] == "appliance"
    comp = asset_to_component_dict(make_asset(attributes={}, asset_type="whatever"))
    assert comp["role"] == "unknown"
    comp = asset_to_component_dict(make_asset(attributes={"legacy_role": "hypervisor"}))
    assert comp["role"] == "hypervisor"


def test_mcp_block_reconstruction():
    asset = make_asset(
        managed=True,
        mcp_config={"vendor": "fortinet", "appliance": "fortigate",
                    "device_type": "fortios", "os_version": "7.4.5",
                    "host": "10.0.0.1", "port": 443, "verify_ssl": False,
                    "primary": True, "sync_warnings": ["w1"]},
        sync_status="synced",
        sync_error=None,
        last_synced_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    mcp = asset_to_component_dict(asset)["metadata"]["mcp"]
    # exactly what pack_matching.py and assessments read today
    assert mcp["managed"] is True
    assert mcp["device_type"] == "fortios"
    assert mcp["os_version"] == "7.4.5"
    assert mcp["sync"]["status"] == "synced"
    assert mcp["sync"]["warnings"] == ["w1"]
    assert mcp["sync"]["last_synced_at"].startswith("2026-07-29")
    assert "token" not in str(mcp)


async def test_assemble_excludes_deleted_and_dangling(asset_session_factory):
    async with asset_session_factory() as s:
        s.add(make_asset())
        s.add(make_asset(id="sw1", ref="sw_core", name="SW", asset_type="switch",
                         attributes={"legacy_role": "switch"}))
        s.add(make_asset(id="gone", ref="gone", name="Gone", asset_type="generic",
                         attributes={}, deleted_at=datetime.now(timezone.utc)))
        s.add(AssetRelationORM(customer_id="t1", source_asset_id="fw1",
                               target_asset_id="sw1", relation_type="connects_to",
                               details={"note": "uplink"}))
        s.add(AssetRelationORM(customer_id="t1", source_asset_id="fw1",
                               target_asset_id="gone", relation_type="depends_on"))
        await s.commit()

        components, dependencies = await assemble_inventory(s, "t1")
        assert {c["id"] for c in components} == {"fw1", "sw1"}
        assert dependencies == [{
            "source_id": "fw1", "target_id": "sw1",
            "relation": "connects_to", "metadata": {"note": "uplink"},
        }]


async def test_subitems_aggregate_in_component_metadata(asset_session_factory):
    """Discovered sub-inventory reaches the agent as a compact aggregate on
    the parent component — never as components of its own."""
    import uuid as _uuid

    async with asset_session_factory() as s:
        s.add(make_asset(id="edr1", ref="edr_console", name="EDR",
                         asset_type="edr_console", attributes={}))
        for state, absent in (("Running", False), ("Disconnected", True)):
            s.add(AssetSubitemORM(
                id=_uuid.uuid4().hex, customer_id="t1", parent_asset_id="edr1",
                source="fortiedr", kind="endpoint",
                external_id=_uuid.uuid4().hex, name="EP",
                state=state, absent=absent, attributes={},
            ))
        await s.commit()

        components, _ = await assemble_inventory(s, "t1")
        assert [c["id"] for c in components] == ["edr1"], \
            "subitems must not appear as components"
        agg = components[0]["metadata"]["subitems"]["endpoint"]
        assert agg["total"] == 2
        assert agg["by_state"] == {"Running": 1, "Disconnected": 1}
        assert agg["absent"] == 1
        # the aggregate survives Component hydration (free-form metadata)
        Component(**components[0])


async def test_context_store_overlay(asset_session_factory):
    """get_active_context: blob keeps baselines/known_changes, assets tables
    override inventory/dependencies; save_context never persists them."""
    async with asset_session_factory() as s:
        # Pre-migration-style blob with a STALE component copy
        s.add(ClientContextORM(customer_id="t1", version="3", is_active=True, content={
            "customer_id": "t1", "version": "3",
            "inventory": [{"id": "stale", "ref": "stale", "role": "server",
                           "priority": 1, "metadata": {}}],
            "dependencies": [],
            "baselines": [{"component_id": "fw1", "metric": "cpu",
                           "normal_value": "<60%", "description": ""}],
            "known_changes": [],
        }))
        s.add(make_asset())
        await s.commit()

        store = ContextStore(s)
        ctx = await store.get_active_context("t1")
        assert [c.id for c in ctx.inventory] == ["fw1"], "stale blob copy must be inert"
        assert ctx.baselines[0].metric == "cpu"

        # save drops inventory/dependencies from the persisted blob.
        # (Saved under t2: sqlite renders the Postgres partial unique index
        # on client_contexts as a full unique index, so re-saving t1 here
        # would trip it — a fixture artifact, not a code path.)
        ctx.customer_id = "t2"
        ctx.version = "4"
        row = await store.save_context(ctx)
        assert row.content["inventory"] == [] and row.content["dependencies"] == []
        assert row.content["baselines"][0]["metric"] == "cpu"

        # reads keep assembling inventory from the tables
        ctx2 = await store.get_active_context("t1")
        assert [c.id for c in ctx2.inventory] == ["fw1"]


async def test_assets_without_blob_still_yield_context(asset_session_factory):
    async with asset_session_factory() as s:
        s.add(make_asset())
        await s.commit()
        ctx = await ContextStore(s).get_active_context("t1")
        assert isinstance(ctx, ClientContext)
        assert [c.id for c in ctx.inventory] == ["fw1"]

        # and a tenant with neither blob nor assets keeps returning None
        assert await ContextStore(s).get_active_context("t2") is None
