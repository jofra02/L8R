"""Asset definition registry tests (pure + sqlite snapshot sync).

Covers: shipped YAML validity, schema validation failures (reserved keys,
enum rules, required-needs-default), pack cross-validation (unknown steps /
normalizers / non-read-only tools), content-hash stability and the
immutability contract.

Run: uv run pytest src/testing/test_assets_definitions.py
"""

import pytest

from src.assets import registry
from src.assets.schema import (
    AssetTypeDefinition,
    EnrichmentPackDefinition,
    FieldMapping,
)


def test_shipped_definitions_load():
    files = registry.discover_files()
    kinds = {k for k, _ in files}
    assert kinds == {registry.KIND_ASSET_TYPE, registry.KIND_ENRICHMENT_PACK}
    type_ids = set()
    pack_ids = set()
    for kind, path in files:
        if kind == registry.KIND_ASSET_TYPE:
            type_ids.add(registry.load_type_file(path).type_id)
        else:
            pack_ids.add(registry.load_pack_file(path).pack_id)
    assert {"firewall", "switch", "router", "access_point", "server",
            "endpoint", "edr_console", "generic"} <= type_ids
    assert {"fortigate", "fortiedr"} <= pack_ids


def test_fortigate_pack_declares_managed_ap_and_switch_subitems():
    # v4 contract: managed FortiAPs/FortiSwitches are discovered as
    # root-level subitems through the frozen monitor-API tool names.
    pack = registry.load_pack_file(registry.PACKS_DIR / "fortigate.yaml")
    assert pack.version >= 4
    tools = {s.id: s.tool for s in pack.steps}
    assert tools["managed_aps"] == "fgt74_cmdb_wifi_get_managed_ap"
    assert tools["managed_switches"] == "fgt74_cmdb_switch_get_controller_managed_status"
    required = {s.id for s in pack.steps if s.required}
    assert {"managed_aps", "managed_switches"}.isdisjoint(required)
    rules = {r.kind: r for r in pack.subitems}
    assert set(rules) == {"access_point", "switch"}
    assert rules["access_point"].step == "managed_aps"
    assert rules["switch"].step == "managed_switches"
    for rule in rules.values():
        assert rule.identity.source == "fortigate"
        assert rule.identity.external_id == "serial"
        assert rule.parent is None  # root-only (nested conversion is backlog #4)


def test_type_field_validation_rules():
    base = {"type_id": "x", "version": 1, "label": "X"}
    with pytest.raises(Exception, match="shadows"):
        AssetTypeDefinition.model_validate({**base, "fields": [{"key": "serial_number"}]})
    with pytest.raises(Exception, match="snake_case"):
        AssetTypeDefinition.model_validate({**base, "fields": [{"key": "BadKey"}]})
    with pytest.raises(Exception, match="enum type requires"):
        AssetTypeDefinition.model_validate({**base, "fields": [{"key": "e", "type": "enum"}]})
    with pytest.raises(Exception, match="must declare a default"):
        AssetTypeDefinition.model_validate({**base, "fields": [{"key": "r", "required": True}]})
    with pytest.raises(Exception, match="duplicate field keys"):
        AssetTypeDefinition.model_validate({**base, "fields": [{"key": "a"}, {"key": "a"}]})


def test_pack_cross_validation():
    base = {
        "pack_id": "p", "version": 1, "label": "P",
        "compatible": {"device_types": ["x"], "asset_types": []},
        "steps": [{"id": "s1", "tool": "fgt74_monitor_sys_get_status"}],
    }
    with pytest.raises(Exception, match="unknown step"):
        EnrichmentPackDefinition.model_validate({
            **base, "mappings": [{"source": "ghost.results", "target": "name"}],
        })
    with pytest.raises(Exception, match="unknown dependency"):
        EnrichmentPackDefinition.model_validate({
            **base,
            "steps": [{"id": "s1", "tool": "fgt74_monitor_sys_get_status",
                       "depends_on": ["nope"]}],
        })


def test_mapping_target_and_transform_whitelist():
    with pytest.raises(Exception, match="mapping target"):
        FieldMapping.model_validate({"source": "a.b", "target": "customer_id"})
    with pytest.raises(Exception, match="unknown transform"):
        FieldMapping.model_validate({"source": "a.b", "target": "name", "transform": "eval"})
    ok = FieldMapping.model_validate({"source": "a.b", "target": "attributes.os"})
    assert ok.policy == "manual_wins"


def test_pack_rejects_non_readonly_tool(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "pack_id: bad\nversion: 1\nlabel: Bad\n"
        "compatible: {device_types: [x], asset_types: []}\n"
        "steps:\n  - {id: s1, tool: fgt74_cmdb_sys_put_global}\n",
        encoding="utf-8",
    )
    with pytest.raises(registry.AssetDefinitionValidationError, match="read-only"):
        registry.load_pack_file(bad)


def test_pack_rejects_unknown_normalizer(tmp_path):
    bad = tmp_path / "bad2.yaml"
    bad.write_text(
        "pack_id: bad2\nversion: 1\nlabel: Bad\n"
        "compatible: {device_types: [x], asset_types: []}\n"
        "steps:\n  - {id: s1, tool: fgt74_monitor_sys_get_status, normalizer: nope.nope}\n",
        encoding="utf-8",
    )
    with pytest.raises(registry.AssetDefinitionValidationError, match="unknown normalizer"):
        registry.load_pack_file(bad)


def test_content_hash_stable():
    files = registry.discover_files()
    _, path = next((k, p) for k, p in files if k == registry.KIND_ASSET_TYPE)
    a = registry.content_hash(registry.load_type_file(path))
    b = registry.content_hash(registry.load_type_file(path))
    assert a == b and len(a) == 64


async def test_sync_and_immutability(asset_session_factory, tmp_path, monkeypatch):
    # First sync creates, second is unchanged, content drift is rejected.
    types_dir = tmp_path / "types"
    types_dir.mkdir()
    (tmp_path / "packs").mkdir()
    f = types_dir / "widget.yaml"
    f.write_text("type_id: widget\nversion: 1\nlabel: Widget\n", encoding="utf-8")

    async with asset_session_factory() as s:
        out = await registry.sync_definitions(s, base_dir=tmp_path)
        assert out == {"asset_type:widget@1": "created"}
        out = await registry.sync_definitions(s, base_dir=tmp_path)
        assert out == {"asset_type:widget@1": "unchanged"}

        f.write_text("type_id: widget\nversion: 1\nlabel: Widget v2\n", encoding="utf-8")
        with pytest.raises(registry.AssetDefinitionImmutabilityError):
            await registry.sync_definitions(s, base_dir=tmp_path)

        f.write_text("type_id: widget\nversion: 2\nlabel: Widget v2\n", encoding="utf-8")
        out = await registry.sync_definitions(s, base_dir=tmp_path)
        assert out == {"asset_type:widget@2": "created"}

        latest = await registry.get_latest_type(s, "widget")
        assert latest.version == 2 and latest.label == "Widget v2"
