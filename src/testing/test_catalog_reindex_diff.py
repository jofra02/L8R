"""index_tools description/schema-change detection (no DB, no network, no LLM).

The startup diff must re-index a tool whose indexed description no longer
matches the registry description OR whose args schema fingerprint drifted
(e.g. a gateway pack enriched an enum or a parameter description), keep
skipping unchanged tools, respect TOOL_CATALOG_REINDEX_CAP, and not treat the
`description or name` payload fallback as a change. External tools' raw MCP
inputSchema must be the schema source (the pydantic args_schema round-trip is
a typeless shell).

Run: uv run pytest src/testing/test_catalog_reindex_diff.py
"""

import src.core.registry as registry_mod
from src.config import settings
from src.core.qdrant import vector_store, tool_schema_hash
from src.core.registry import CapabilityRegistry

EMPTY_SCHEMA_HASH = tool_schema_hash({})


class FakeTool:
    def __init__(self, name, description, input_schema=None):
        self.name = name
        self.description = description
        self.args_schema = None
        self.input_schema = input_schema
        self.server_name = "mcp-gateway"


class BatchRecorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, texts, metadatas, ids, customer_id):
        self.calls.append({"texts": texts, "metadatas": metadatas, "ids": ids})

    @property
    def indexed_names(self):
        return [m["tool_name"] for call in self.calls for m in call["metadatas"]]


def _expected_id(name):
    return vector_store._generate_id(f"__global__-{name}")


async def _run_index_tools(monkeypatch, tools, indexed_descriptions):
    recorder = BatchRecorder()

    async def fake_descriptions(cid):
        # Accept the shorthand `name -> description` and expand it to the
        # payload shape, defaulting schema_hash to the schema-less fingerprint
        # (matches FakeTool without input_schema, i.e. "no schema drift").
        out = {}
        for name, val in indexed_descriptions.items():
            if isinstance(val, dict):
                out[name] = val
            else:
                out[name] = {"description": val, "schema_hash": EMPTY_SCHEMA_HASH}
        return out

    async def no_migration(cid):
        return False

    async def fake_classify(cls, metadatas):
        return [
            {"categories": [], "tier": 0, "provides_identifiers": [],
             "requires_identifiers": [], "scope_params": []}
            for _ in metadatas
        ]

    monkeypatch.setattr(vector_store, "get_indexed_tool_descriptions", fake_descriptions)
    monkeypatch.setattr(vector_store, "_check_catalog_needs_migration", no_migration)
    monkeypatch.setattr(vector_store, "batch_index_tools", recorder)
    monkeypatch.setattr(
        registry_mod.CapabilityRegistry, "list_tools", classmethod(lambda cls: tools)
    )
    monkeypatch.setattr(
        registry_mod.CapabilityRegistry, "_classify_tools_via_llm", classmethod(fake_classify)
    )

    await CapabilityRegistry.index_tools()
    return recorder


async def test_changed_description_is_reindexed(monkeypatch):
    tools = [FakeTool("tool_a", "new enriched description")]
    recorder = await _run_index_tools(monkeypatch, tools, {"tool_a": "old description"})

    assert recorder.indexed_names == ["tool_a"]
    assert recorder.calls[0]["ids"] == [_expected_id("tool_a")]
    assert "new enriched description" in recorder.calls[0]["texts"][0]


async def test_unchanged_catalog_skips_indexing(monkeypatch):
    tools = [FakeTool("tool_a", "same description")]
    recorder = await _run_index_tools(monkeypatch, tools, {"tool_a": "same description"})

    assert recorder.calls == []


async def test_description_fallback_to_name_is_not_a_change(monkeypatch):
    # Payload stores `description or name`; a tool without description must
    # compare against its name, not against "".
    tools = [FakeTool("tool_a", None)]
    recorder = await _run_index_tools(monkeypatch, tools, {"tool_a": "tool_a"})

    assert recorder.calls == []


async def test_new_and_changed_are_indexed_together(monkeypatch):
    tools = [FakeTool("tool_new", "brand new"), FakeTool("tool_b", "changed")]
    recorder = await _run_index_tools(monkeypatch, tools, {"tool_b": "original"})

    assert sorted(recorder.indexed_names) == ["tool_b", "tool_new"]


async def test_reindex_cap_defers_excess_changed_tools(monkeypatch):
    monkeypatch.setattr(settings, "TOOL_CATALOG_REINDEX_CAP", 2)
    tools = [FakeTool(f"tool_{i}", "changed") for i in range(4)]
    indexed = {f"tool_{i}": "original" for i in range(4)}
    recorder = await _run_index_tools(monkeypatch, tools, indexed)

    # Alphabetical order makes cross-startup progress deterministic.
    assert sorted(recorder.indexed_names) == ["tool_0", "tool_1"]


SCHEMA = {
    "properties": {
        "timeFilter": {"type": "string", "enum": ["Last7days", "All"],
                       "description": "Time window"},
    },
    "required": [],
}


async def test_changed_schema_same_description_is_reindexed(monkeypatch):
    # A pack enriched an enum: description identical, schema fingerprint moved.
    tools = [FakeTool("tool_a", "same description", input_schema=SCHEMA)]
    recorder = await _run_index_tools(monkeypatch, tools, {
        "tool_a": {"description": "same description", "schema_hash": EMPTY_SCHEMA_HASH},
    })

    assert recorder.indexed_names == ["tool_a"]
    # The raw MCP inputSchema is what lands in the payload, hash included.
    meta = recorder.calls[0]["metadatas"][0]
    assert meta["args_schema"] == SCHEMA
    assert meta["schema_hash"] == tool_schema_hash(SCHEMA)


async def test_unchanged_schema_is_skipped(monkeypatch):
    tools = [FakeTool("tool_a", "same description", input_schema=SCHEMA)]
    recorder = await _run_index_tools(monkeypatch, tools, {
        "tool_a": {"description": "same description",
                   "schema_hash": tool_schema_hash(SCHEMA)},
    })

    assert recorder.calls == []


async def test_missing_schema_hash_counts_as_change(monkeypatch):
    # Points indexed before schema_hash existed carry typeless shells — they
    # must be re-indexed (subject to the cap) even if the description matches.
    tools = [FakeTool("tool_a", "same description", input_schema=SCHEMA)]
    recorder = await _run_index_tools(monkeypatch, tools, {
        "tool_a": {"description": "same description", "schema_hash": ""},
    })

    assert recorder.indexed_names == ["tool_a"]
