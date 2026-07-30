"""Pure mapping-engine tests: path extraction, transforms, merge policy.

Run: uv run pytest src/testing/test_assets_mappings.py
"""

from src.assets.enrichment import mappings as mp
from src.assets.schema import FieldMapping
from src.core.orm import AssetORM

DATA = {
    "results": [
        {"id": 1, "macAddresses": ["aa:bb"], "nested": {"x": 5}},
        {"id": 2, "macAddresses": []},
    ],
    "meta": {"serial": "FG100", "version": "v7.4.5"},
}


def test_extract_path():
    assert mp.extract_path(DATA, "meta.serial") == "FG100"
    assert mp.extract_path(DATA, "results[0].nested.x") == 5
    assert mp.extract_path(DATA, "results[0].macAddresses[0]") == "aa:bb"
    assert mp.extract_path(DATA, "results[5].id") is None
    assert mp.extract_path(DATA, "missing.path") is None
    assert mp.extract_items(DATA, "results[*]") == DATA["results"]
    assert mp.extract_items({"results": {"a": 1}}, "results[*]") == [{"a": 1}]
    assert mp.extract_items(DATA, "ghost[*]") == []


def test_transforms():
    assert mp.apply_transform("ABC", "lowercase") == "abc"
    assert mp.apply_transform(["x", "y"], "first") == "x"
    assert mp.apply_transform([], "first") is None
    assert mp.apply_transform(["a", "b"], "join") == "a, b"
    # epoch ms vs seconds
    assert mp.apply_transform(1785325353000, "to_datetime").startswith("2026-07-2")
    assert mp.apply_transform(1785325353, "to_date").startswith("2026-07-2")
    assert mp.apply_transform("2026-07-29T10:00:00Z", "to_datetime") == "2026-07-29T10:00:00+00:00"
    assert mp.apply_transform("garbage", "to_datetime") is None
    assert mp.apply_transform("Running", None, {"Running": "ok"}) == "ok"


def make_asset(**kw) -> AssetORM:
    defaults = dict(id="a1", customer_id="t1", name="A", ref="a", asset_type="generic",
                    attributes={}, provenance={}, tags=[])
    defaults.update(kw)
    return AssetORM(**defaults)


def test_merge_manual_wins_skips_manual_value():
    asset = make_asset(serial_number="MANUAL-1",
                       provenance={"serial_number": {"source": "manual"}})
    m = FieldMapping(source="meta.serial", target="serial_number", policy="manual_wins")
    changed = mp.merge_field(asset, m, "FG100", pack_id="p", run_id="r")
    assert changed is False and asset.serial_number == "MANUAL-1"


def test_merge_manual_wins_treats_unknown_provenance_as_manual():
    # Backfilled data has no provenance entry — never clobber it.
    asset = make_asset(serial_number="LEGACY")
    m = FieldMapping(source="meta.serial", target="serial_number", policy="manual_wins")
    assert mp.merge_field(asset, m, "FG100", pack_id="p", run_id="r") is False
    assert asset.serial_number == "LEGACY"


def test_merge_manual_wins_fills_empty_and_updates_discovered():
    asset = make_asset()
    m = FieldMapping(source="meta.serial", target="serial_number", policy="manual_wins")
    assert mp.merge_field(asset, m, "FG100", pack_id="p", run_id="r1") is True
    assert asset.serial_number == "FG100"
    assert asset.provenance["serial_number"]["source"] == "discovered"
    # discovered value updates on the next run under manual_wins
    assert mp.merge_field(asset, m, "FG200", pack_id="p", run_id="r2") is True
    assert asset.serial_number == "FG200"
    assert asset.provenance["serial_number"]["run_id"] == "r2"


def test_merge_discovered_wins_overwrites_manual():
    asset = make_asset(serial_number="MANUAL",
                       provenance={"serial_number": {"source": "manual"}})
    m = FieldMapping(source="meta.serial", target="serial_number", policy="discovered_wins")
    assert mp.merge_field(asset, m, "FG100", pack_id="p", run_id="r") is True
    assert asset.serial_number == "FG100"


def test_merge_attribute_target():
    asset = make_asset()
    m = FieldMapping(source="meta.version", target="attributes.os_version")
    assert mp.merge_field(asset, m, "v7.4.5", pack_id="p", run_id="r") is True
    assert asset.attributes["os_version"] == "v7.4.5"
    assert asset.provenance["attributes.os_version"]["source"] == "discovered"


def test_merge_none_and_equal_values_noop():
    asset = make_asset(serial_number="X",
                       provenance={"serial_number": {"source": "discovered"}})
    m = FieldMapping(source="meta.serial", target="serial_number")
    assert mp.merge_field(asset, m, None, pack_id="p", run_id="r") is False
    assert mp.merge_field(asset, m, "X", pack_id="p", run_id="r") is False


def test_apply_mappings_counts():
    asset = make_asset()
    mappings = [
        FieldMapping(source="meta.serial", target="serial_number"),
        FieldMapping(source="meta.version", target="attributes.os_version"),
        FieldMapping(source="ghost.path", target="attributes.nope"),
    ]
    changed, fields = mp.apply_mappings(asset, mappings, DATA, pack_id="p", run_id="r")
    assert changed == 2
    assert set(fields) == {"serial_number", "attributes.os_version"}
