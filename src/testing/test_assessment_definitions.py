"""Assessment definition format: schema validation, reference resolution,
content hashing and sync immutability (no DB, no network).

Run: uv run pytest src/testing/test_assessment_definitions.py
"""

import pytest

from src.assessments.registry import (
    DefinitionImmutabilityError,
    DefinitionValidationError,
    content_hash,
    discover_definition_files,
    load_definition_file,
    sync_definitions,
)
from src.assessments.schema import AssessmentDefinitionModel

BASE_DEF = {
    "assessment": {
        "id": "test-def", "version": "1.0.0", "name": "Test",
        "vendor": "fortinet", "product": "fortigate",
    },
    "collection_steps": [
        {"id": "a", "tool": "fgt74_x_get_a", "required": True,
         "normalizer": "fortigate.cmdb_results"},
        {"id": "b", "tool": "fgt74_x_get_b", "depends_on": ["a"]},
    ],
    "controls": [
        {"id": "C-1", "title": "t", "category": "cat", "severity": "high",
         "required_evidence": ["a"],
         "evaluation": {"type": "rule", "rule": "fortigate.ntp_rule"}},
    ],
}


def _clone(overrides=None):
    import copy
    data = copy.deepcopy(BASE_DEF)
    for path, value in (overrides or {}).items():
        node = data
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[int(k)] if k.isdigit() else node[k]
        node[keys[-1]] = value
    return data


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_valid_definition_parses():
    model = AssessmentDefinitionModel.model_validate(BASE_DEF)
    assert model.assessment.id == "test-def"
    assert model.categories == ["cat"]


def test_unknown_dependency_rejected():
    data = _clone({"collection_steps.1.depends_on": ["missing"]})
    with pytest.raises(Exception, match="unknown step"):
        AssessmentDefinitionModel.model_validate(data)


def test_unknown_evidence_reference_rejected():
    data = _clone({"controls.0.required_evidence": ["nope"]})
    with pytest.raises(Exception, match="unknown evidence step"):
        AssessmentDefinitionModel.model_validate(data)


def test_hybrid_requires_rule_and_instructions():
    data = _clone({"controls.0.evaluation": {"type": "hybrid", "rule": "r"}})
    with pytest.raises(Exception, match="hybrid"):
        AssessmentDefinitionModel.model_validate(data)


def test_duplicate_step_ids_rejected():
    data = _clone()
    data["collection_steps"].append({"id": "a", "tool": "fgt74_x_get_c"})
    with pytest.raises(Exception, match="duplicate"):
        AssessmentDefinitionModel.model_validate(data)


# ---------------------------------------------------------------------------
# File loading + reference resolution
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path, data, name="def.yaml"):
    import yaml
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_unknown_rule_name_rejected_at_load(tmp_path):
    data = _clone({"controls.0.evaluation": {"type": "rule", "rule": "no.such_rule"}})
    path = _write_yaml(tmp_path, data)
    with pytest.raises(DefinitionValidationError, match="unknown rule"):
        load_definition_file(path)


def test_unknown_normalizer_rejected_at_load(tmp_path):
    data = _clone({"collection_steps.0.normalizer": "no.such_normalizer"})
    path = _write_yaml(tmp_path, data)
    with pytest.raises(DefinitionValidationError, match="unknown normalizer"):
        load_definition_file(path)


def test_shipped_definitions_are_valid():
    files = discover_definition_files()
    assert files, "no shipped definitions found"
    for path in files:
        model = load_definition_file(path)
        assert model.controls and model.collection_steps


def test_content_hash_is_stable_and_semantic(tmp_path):
    model_a = AssessmentDefinitionModel.model_validate(BASE_DEF)
    model_b = AssessmentDefinitionModel.model_validate(_clone())
    assert content_hash(model_a) == content_hash(model_b)
    changed = AssessmentDefinitionModel.model_validate(
        _clone({"controls.0.severity": "low"})
    )
    assert content_hash(changed) != content_hash(model_a)


# ---------------------------------------------------------------------------
# Sync immutability (fake session)
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    def __init__(self, existing_by_key):
        self.existing_by_key = existing_by_key
        self.added = []
        self.committed = False
        self._pending_key = None

    async def execute(self, stmt):
        # Extract (definition_id, version) from the compiled where-clause params
        params = stmt.compile().params
        key = (params.get("definition_id_1"), params.get("version_1"))
        return _FakeResult(self.existing_by_key.get(key))

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


class _Existing:
    def __init__(self, content_hash):
        self.content_hash = content_hash


async def test_sync_creates_new_version(tmp_path):
    _write_yaml(tmp_path, _clone())
    session = _FakeSession({})
    outcome = await sync_definitions(session, base_dir=tmp_path)
    assert outcome == {"test-def@1.0.0": "created"}
    assert len(session.added) == 1 and session.committed


async def test_sync_unchanged_version_is_noop(tmp_path):
    _write_yaml(tmp_path, _clone())
    digest = content_hash(AssessmentDefinitionModel.model_validate(BASE_DEF))
    session = _FakeSession({("test-def", "1.0.0"): _Existing(digest)})
    outcome = await sync_definitions(session, base_dir=tmp_path)
    assert outcome == {"test-def@1.0.0": "unchanged"}
    assert not session.added


async def test_sync_rejects_changed_content_without_version_bump(tmp_path):
    _write_yaml(tmp_path, _clone({"controls.0.severity": "low"}))
    original_digest = content_hash(AssessmentDefinitionModel.model_validate(BASE_DEF))
    session = _FakeSession({("test-def", "1.0.0"): _Existing(original_digest)})
    with pytest.raises(DefinitionImmutabilityError, match="version bump"):
        await sync_definitions(session, base_dir=tmp_path)
