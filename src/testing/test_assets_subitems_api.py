"""AssetService sub-inventory tests (in-memory sqlite, no network).

Covers: list_subitems filters (kind/state/q/absent), pagination, tenant
isolation (404), and compute_subitems_summary shape (multi-kind, by_state,
absent counts, empty short-circuit).

Run: uv run pytest src/testing/test_assets_subitems_api.py
"""

import uuid

import pytest

from src.api.exceptions import APIError
from src.api.schemas.assets import AssetCreate
from src.assets.registry import sync_definitions
from src.assets.service import AssetService, compute_subitems_summary
from src.core.orm import AssetSubitemORM


@pytest.fixture()
async def session(asset_session_factory):
    async with asset_session_factory() as s:
        await sync_definitions(s)
        yield s


def add_subitem(session, parent_id, *, customer_id="t1", kind="endpoint",
                source="fortiedr", external_id=None, name="EP",
                state=None, absent=False, attributes=None):
    session.add(AssetSubitemORM(
        id=uuid.uuid4().hex, customer_id=customer_id, parent_asset_id=parent_id,
        source=source, kind=kind, external_id=external_id or uuid.uuid4().hex,
        name=name, state=state, absent=absent, attributes=attributes or {},
    ))


async def make_console(session, customer_id="t1", ref=None) -> str:
    svc = AssetService(session)
    asset = await svc.create_asset(customer_id, AssetCreate(
        name="EDR", ref=ref or f"edr-{uuid.uuid4().hex[:6]}",
        asset_type="edr_console",
    ), "user:u1")
    return asset.id


async def test_list_subitems_filters(session):
    svc = AssetService(session)
    parent = await make_console(session)
    add_subitem(session, parent, name="PC-ALPHA", state="Running",
                external_id="1")
    add_subitem(session, parent, name="PC-BETA", state="Disconnected",
                external_id="2", absent=True)
    add_subitem(session, parent, name="SRV-GAMMA", state="Running",
                external_id="3", kind="server_agent")
    await session.commit()

    rows, total = await svc.list_subitems("t1", parent, page=1, page_size=10)
    assert total == 3 and [r.name for r in rows] == ["PC-ALPHA", "PC-BETA", "SRV-GAMMA"]

    rows, total = await svc.list_subitems("t1", parent, filters={"kind": "endpoint"},
                                          page=1, page_size=10)
    assert total == 2

    rows, total = await svc.list_subitems("t1", parent, filters={"state": "Running"},
                                          page=1, page_size=10)
    assert total == 2

    rows, total = await svc.list_subitems("t1", parent, filters={"absent": True},
                                          page=1, page_size=10)
    assert total == 1 and rows[0].name == "PC-BETA"

    rows, total = await svc.list_subitems("t1", parent, filters={"q": "alpha"},
                                          page=1, page_size=10)
    assert total == 1 and rows[0].name == "PC-ALPHA"

    rows, total = await svc.list_subitems("t1", parent, page=1, page_size=2)
    assert total == 3 and len(rows) == 2


async def test_list_subitems_tenant_isolation(session):
    svc = AssetService(session)
    parent = await make_console(session, customer_id="t1")
    with pytest.raises(APIError) as e:
        await svc.list_subitems("t2", parent, page=1, page_size=10)
    assert e.value.status_code == 404


async def test_subitems_summary_shape(session):
    parent_a = await make_console(session)
    parent_b = await make_console(session)
    for state, absent in (("Running", False), ("Running", False),
                          ("Disconnected", True), (None, False)):
        add_subitem(session, parent_a, state=state, absent=absent)
    add_subitem(session, parent_a, kind="server_agent", state="Running")
    add_subitem(session, parent_b, state="Running")
    await session.commit()

    out = await compute_subitems_summary(session, [parent_a, parent_b], "t1")
    a = out[parent_a]
    assert a["endpoint"]["total"] == 4
    assert a["endpoint"]["by_state"] == {"Running": 2, "Disconnected": 1, "unknown": 1}
    assert a["endpoint"]["absent"] == 1
    assert a["server_agent"]["total"] == 1
    assert out[parent_b]["endpoint"]["total"] == 1

    # empty short-circuit
    assert await compute_subitems_summary(session, [], "t1") == {}
    # parents without subitems simply have no entry
    assert parent_b in out and len(out) == 2
