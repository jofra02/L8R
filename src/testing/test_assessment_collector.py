"""Collection engine: dependency waves, retry policy, dedup, skip propagation
and sanitized evidence persistence — all DB access faked in-memory.

Run: uv run pytest src/testing/test_assessment_collector.py
"""

import pytest

import src.assessments.collector as collector_mod
from src.assessments.collector import CollectionEngine, topo_waves
from src.assessments.schema import AssessmentDefinitionModel
from src.core.mcp_executor import MCPToolResult


def _definition(steps):
    return AssessmentDefinitionModel.model_validate({
        "assessment": {"id": "d", "version": "1.0.0", "name": "d",
                       "vendor": "fortinet", "product": "fortigate"},
        "collection_steps": steps,
        "controls": [{
            "id": "C-1", "title": "t", "category": "c", "severity": "low",
            "evaluation": {"type": "rule", "rule": "fortigate.ntp_rule"},
        }],
    })


class _Target:
    def __init__(self, id="t1", device_name="fw1", component_id="asset-1"):
        self.id = id
        self.device_name = device_name       # display label only
        self.component_id = component_id     # gateway routing identity


class InMemoryEngine(CollectionEngine):
    """CollectionEngine with the DB layer replaced by dicts."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = {}          # (target_id, step_id) -> dict
        self.target_status = {}

    async def _get_existing(self, target_id, step_id):
        row = self.rows.get((target_id, step_id))
        if row is None:
            return None
        return type("Row", (), row)

    async def _upsert_execution(self, target_id, step, **fields):
        key = (target_id, step.id)
        row = self.rows.setdefault(key, {"id": f"exec-{step.id}-{target_id}",
                                         "tool_name": step.tool})
        row.update(fields)
        return row["id"]

    async def _bump_progress(self, failed):
        async with self._progress_lock:
            self._steps_done += 1
            if failed:
                self._steps_failed += 1

    async def _set_target_status(self, target_id, status, error=None):
        self.target_status[target_id] = (status, error)

    async def _cancel_pending(self, target_id):
        pass


class _FakeEvidenceStore:
    saved = []

    def __init__(self, **kwargs):
        pass

    async def save_evidence(self, tool_name, tool_args, content, summary=None):
        _FakeEvidenceStore.saved.append({"tool": tool_name, "content": content})
        return type("Snap", (), {"content_hash": "f" * 64, "id": "ev_fake"})


@pytest.fixture(autouse=True)
def _fake_evidence(monkeypatch):
    _FakeEvidenceStore.saved = []
    import src.core.evidence_store as ev_mod
    monkeypatch.setattr(ev_mod, "EvidenceStore", _FakeEvidenceStore)


def _executor(script):
    """script: list of MCPToolResult (or callables) consumed per call."""
    calls = []

    async def fake_execute(tool_name, args, customer_id, *, enforce_read_only=False,
                           timeout_s=None):
        calls.append({"tool": tool_name, "args": args, "tenant": customer_id,
                      "read_only": enforce_read_only})
        item = script.pop(0) if script else MCPToolResult(ok=True, content={"results": []})
        return item

    fake_execute.calls = calls
    return fake_execute


# ---------------------------------------------------------------------------

def test_topo_waves_orders_dependencies():
    steps = _definition([
        {"id": "a", "tool": "x_get_a"},
        {"id": "b", "tool": "x_get_b", "depends_on": ["a"]},
        {"id": "c", "tool": "x_get_c", "depends_on": ["b"]},
    ]).collection_steps
    waves = topo_waves(steps)
    assert [[s.id for s in w] for w in waves] == [["a"], ["b"], ["c"]]


def test_topo_waves_detects_cycles():
    from src.assessments.schema import CollectionStepDef
    steps = [
        CollectionStepDef(id="a", tool="x_get_a", depends_on=["b"]),
        CollectionStepDef(id="b", tool="x_get_b", depends_on=["a"]),
    ]
    with pytest.raises(ValueError, match="cycle"):
        topo_waves(steps)


async def test_happy_path_collects_and_normalizes(monkeypatch):
    definition = _definition([
        {"id": "a", "tool": "x_get_a", "required": True,
         "normalizer": "fortigate.cmdb_results"},
    ])
    payload = {"results": [{"name": "row1"}], "vdom": "root"}
    monkeypatch.setattr(collector_mod, "execute_mcp_tool",
                        _executor([MCPToolResult(ok=True, content=payload)]))

    engine = InMemoryEngine("run1", "acme", definition, [_Target()])
    statuses = await engine.collect()

    assert statuses == {"t1": "collected"}
    row = engine.rows[("t1", "a")]
    assert row["status"] == "success"
    assert row["normalized"]["results"] == [{"name": "row1"}]
    assert row["raw_evidence_sha"] == "f" * 64
    assert _FakeEvidenceStore.saved


async def test_device_arg_and_read_only_enforced(monkeypatch):
    definition = _definition([{"id": "a", "tool": "x_get_a"}])
    fake = _executor([MCPToolResult(ok=True, content={})])
    monkeypatch.setattr(collector_mod, "execute_mcp_tool", fake)

    engine = InMemoryEngine("run1", "acme", definition,
                            [_Target(device_name="fgt_lab", component_id="a1b2c3")])
    await engine.collect()

    call = fake.calls[0]
    # Routing must use the component/asset id — never the display name.
    assert call["args"]["device"] == "a1b2c3"
    assert call["read_only"] is True
    assert call["tenant"] == "acme"


async def test_retry_only_on_connection_and_timeout(monkeypatch):
    definition = _definition([{"id": "a", "tool": "x_get_a", "max_attempts": 3}])
    fake = _executor([
        MCPToolResult(ok=False, error="refused", error_type="connection"),
        MCPToolResult(ok=True, content={"results": []}),
    ])
    monkeypatch.setattr(collector_mod, "execute_mcp_tool", fake)
    monkeypatch.setattr(collector_mod.asyncio, "sleep", _instant_sleep)

    engine = InMemoryEngine("run1", "acme", definition, [_Target()])
    statuses = await engine.collect()
    assert statuses == {"t1": "collected"}
    assert len(fake.calls) == 2
    assert engine.rows[("t1", "a")]["status"] == "success"


async def test_no_retry_for_unknown_errors(monkeypatch):
    definition = _definition([{"id": "a", "tool": "x_get_a", "max_attempts": 3}])
    fake = _executor([MCPToolResult(ok=False, error="boom", error_type="unknown")])
    monkeypatch.setattr(collector_mod, "execute_mcp_tool", fake)

    engine = InMemoryEngine("run1", "acme", definition, [_Target()])
    statuses = await engine.collect()
    assert len(fake.calls) == 1
    assert engine.rows[("t1", "a")]["status"] == "failed"
    assert statuses == {"t1": "failed"}


async def test_gateway_error_payload_is_device_error(monkeypatch):
    definition = _definition([{"id": "a", "tool": "x_get_a"}])
    fake = _executor([MCPToolResult(ok=True, content="Error: device 'fw9' not found")])
    monkeypatch.setattr(collector_mod, "execute_mcp_tool", fake)

    engine = InMemoryEngine("run1", "acme", definition, [_Target()])
    await engine.collect()
    row = engine.rows[("t1", "a")]
    assert row["status"] == "failed"
    assert row["error_type"] == "device"


async def test_failed_required_step_skips_dependents(monkeypatch):
    definition = _definition([
        {"id": "a", "tool": "x_get_a", "required": True},
        {"id": "b", "tool": "x_get_b", "depends_on": ["a"]},
    ])
    fake = _executor([MCPToolResult(ok=False, error="down", error_type="device")])
    monkeypatch.setattr(collector_mod, "execute_mcp_tool", fake)

    engine = InMemoryEngine("run1", "acme", definition, [_Target()])
    statuses = await engine.collect()

    assert engine.rows[("t1", "b")]["status"] == "skipped"
    assert "dependency" in engine.rows[("t1", "b")]["error"]
    assert len(fake.calls) == 1  # b never hit the device
    assert statuses == {"t1": "failed"}


async def test_idempotent_reentry_skips_successful_steps(monkeypatch):
    definition = _definition([{"id": "a", "tool": "x_get_a"}])
    fake = _executor([])
    monkeypatch.setattr(collector_mod, "execute_mcp_tool", fake)

    engine = InMemoryEngine("run1", "acme", definition, [_Target()])
    engine.rows[("t1", "a")] = {"id": "prior", "tool_name": "x_get_a", "status": "success"}
    statuses = await engine.collect()

    assert not fake.calls, "successful step must not be re-executed"
    assert statuses == {"t1": "collected"}


async def test_duplicate_tool_args_deduped_in_run(monkeypatch):
    definition = _definition([
        {"id": "a", "tool": "x_get_same"},
        {"id": "b", "tool": "x_get_same"},  # identical tool+args on same device
    ])
    fake = _executor([MCPToolResult(ok=True, content={"results": []})])
    monkeypatch.setattr(collector_mod, "execute_mcp_tool", fake)

    engine = InMemoryEngine("run1", "acme", definition, [_Target()])
    await engine.collect()

    assert len(fake.calls) == 1
    statuses = {engine.rows[("t1", "a")]["status"], engine.rows[("t1", "b")]["status"]}
    assert statuses == {"success", "skipped"}


async def test_sanitize_fields_from_definition(monkeypatch):
    definition = _definition([
        {"id": "a", "tool": "x_get_a", "sanitize": ["secret-token"],
         "normalizer": "fortigate.cmdb_results"},
    ])
    payload = {"results": [{"name": "srv", "secret-token": "hunter2"}]}
    monkeypatch.setattr(collector_mod, "execute_mcp_tool",
                        _executor([MCPToolResult(ok=True, content=payload)]))

    engine = InMemoryEngine("run1", "acme", definition, [_Target()])
    await engine.collect()

    stored = str(_FakeEvidenceStore.saved[0]["content"])
    normalized = str(engine.rows[("t1", "a")]["normalized"])
    assert "hunter2" not in stored
    assert "hunter2" not in normalized


async def _instant_sleep(_seconds):
    return None
