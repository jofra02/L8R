"""Multi-value asset list filters (in-memory sqlite, no network).

Covers: exact IN semantics (asset_type/status/criticality), OR-of-ILIKE
partial matching (name/product_name/model/ip_address/serial_number/owner),
AND across columns, composition with q, comma-string normalization for
internal callers, single-value backward compatibility, `model` sort, and
_collect_filters CSV parsing.

Run: uv run pytest src/testing/test_assets_filters.py
"""

from types import SimpleNamespace

import pytest
from starlette.datastructures import QueryParams

from src.api.exceptions import APIError
from src.api.routers.assets import _collect_filters
from src.api.schemas.assets import AssetCreate
from src.assets.registry import sync_definitions
from src.assets.service import AssetService


@pytest.fixture()
async def session(asset_session_factory):
    async with asset_session_factory() as s:
        await sync_definitions(s)
        yield s


@pytest.fixture()
async def svc(session):
    svc = AssetService(session)
    for spec in (
        dict(name="Branch FW", ref="fw_branch", asset_type="firewall",
             manufacturer="Fortinet", model="FortiGate-100F",
             serial_number="FGT100F001", ip_address="10.0.0.1",
             status="active", criticality="high", owner="netops"),
        dict(name="Core FW", ref="fw_core", asset_type="firewall",
             manufacturer="Fortinet", model="FortiGate-600E",
             serial_number="FGT600E001", ip_address="10.0.0.2",
             status="maintenance", criticality="critical", owner="netops"),
        dict(name="Lobby AP", ref="ap_lobby", asset_type="access_point",
             manufacturer="Fortinet", model="FortiAP-231F",
             serial_number="FAP231F001", ip_address="10.0.1.10",
             status="active", criticality="low", owner="facilities"),
        dict(name="Edge Router", ref="rt_edge", asset_type="router",
             manufacturer="Cisco", model="ISR4331",
             serial_number="CSC4331001", ip_address="192.168.1.1",
             status="retired", criticality="medium", owner="netops"),
    ):
        await svc.create_asset("t1", AssetCreate(**spec), "u")
    return svc


async def _names(svc, filters, **kw):
    rows, _ = await svc.list_assets("t1", filters, page=1, page_size=50, **kw)
    return sorted(r.name for r in rows)


async def test_exact_multi_value_union(svc):
    assert await _names(svc, {"status": ["active", "maintenance"]}) == [
        "Branch FW", "Core FW", "Lobby AP"]
    assert await _names(svc, {"asset_type": ["router", "access_point"]}) == [
        "Edge Router", "Lobby AP"]


async def test_ilike_multi_value_partial_or(svc):
    # the user's canonical example: "fortigate,fortiap" on model
    assert await _names(svc, {"model": ["fortigate", "fortiap"]}) == [
        "Branch FW", "Core FW", "Lobby AP"]
    assert await _names(svc, {"name": ["branch", "edge"]}) == [
        "Branch FW", "Edge Router"]
    assert await _names(svc, {"ip_address": ["10.0.0."]}) == [
        "Branch FW", "Core FW"]
    assert await _names(svc, {"serial_number": ["fgt"]}) == [
        "Branch FW", "Core FW"]
    assert await _names(svc, {"owner": ["ops"]}) == [
        "Branch FW", "Core FW", "Edge Router"]


async def test_filters_and_across_columns(svc):
    assert await _names(svc, {"model": ["forti"], "status": ["active"]}) == [
        "Branch FW", "Lobby AP"]
    assert await _names(svc, {"model": ["fortigate"],
                              "criticality": ["critical"]}) == ["Core FW"]


async def test_q_composes_with_column_filters(svc):
    assert await _names(svc, {"q": "fw", "status": ["maintenance"]}) == ["Core FW"]


async def test_comma_string_normalization(svc):
    # internal callers may pass plain comma-joined strings
    assert await _names(svc, {"status": "active,maintenance"}) == [
        "Branch FW", "Core FW", "Lobby AP"]
    assert await _names(svc, {"model": " fortigate , fortiap "}) == [
        "Branch FW", "Core FW", "Lobby AP"]


async def test_single_value_backward_compat(svc):
    assert await _names(svc, {"asset_type": "firewall"}) == [
        "Branch FW", "Core FW"]
    assert await _names(svc, {"status": ["retired"]}) == ["Edge Router"]
    assert await _names(svc, {}) == [
        "Branch FW", "Core FW", "Edge Router", "Lobby AP"]


async def test_model_sortable(svc):
    rows, _ = await svc.list_assets("t1", {}, page=1, page_size=50, sort="model")
    models = [r.model for r in rows]
    assert models == sorted(models)


async def test_unknown_attr_still_422(svc):
    with pytest.raises(APIError) as e:
        await svc.list_assets("t1", {"attrs": {"nonexistent_attr": "x"}},
                              page=1, page_size=10)
    assert e.value.status_code == 422


def _request(query: str):
    return SimpleNamespace(query_params=QueryParams(query))


def test_collect_filters_csv():
    f = _collect_filters(_request(
        "status=active,maintenance&model=fortigate, fortiap&q=fw&tag=edge&tag=hq"))
    assert f["status"] == ["active", "maintenance"]
    assert f["model"] == ["fortigate", "fortiap"]
    assert f["q"] == "fw"
    assert f["tags"] == ["edge", "hq"]
    assert f["name"] == [] and f["product_name"] == []


def test_collect_filters_empty_and_managed():
    f = _collect_filters(_request(""))
    assert all(f[k] == [] for k in (
        "asset_type", "status", "criticality", "sync_status", "owner",
        "name", "product_name", "model", "manufacturer", "ip_address",
        "serial_number"))
    assert f["managed"] is None
    assert _collect_filters(_request("managed=true"))["managed"] is True


async def test_create_asset_flushes_before_audit_row(asset_session_factory):
    """Regression: the 'created' audit row must never flush before its asset.

    No relationship() links the audit mapper to AssetORM, so INSERT order
    across the two mappers is an unstable property of the flush sort —
    with FK enforcement on (as in Postgres) an audit-first order violates
    asset_audit_log_asset_id_fkey. sqlite only enforces FKs with the
    pragma, hence the explicit enable here.
    """
    from sqlalchemy import text

    async with asset_session_factory() as s:
        await s.execute(text("PRAGMA foreign_keys=ON"))
        await sync_definitions(s)
        svc = AssetService(s)
        asset = await svc.create_asset(
            "t1", AssetCreate(name="fk-order", asset_type="generic"), "user:t1",
        )
        assert asset.id
