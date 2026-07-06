"""Name-freeze regression test.

The Qdrant tool_catalog in support_ai_agent indexes tools by name; any rename
forces a re-index and re-classification. This test builds the whole gateway
offline (no network) and asserts the generated tool-name set is byte-identical
to ``baseline_tools.txt``, captured from the original fortinet_ai_suite server
before the merge.

If this test fails after an intentional change (new specs, fastmcp upgrade),
regenerate the baseline with ``scripts/dump_tools.py`` and plan a Qdrant
re-index in support_ai_agent.
"""

import asyncio
from pathlib import Path

BASELINE = Path(__file__).resolve().parents[2] / "baseline_tools.txt"


def test_tool_names_match_baseline():
    from gateway.app import build_gateway

    gateway = build_gateway()
    tools = asyncio.run(gateway.get_tools())
    names = sorted(tools.keys())

    expected = [line for line in BASELINE.read_text(encoding="utf-8").splitlines() if line]

    missing = sorted(set(expected) - set(names))
    added = sorted(set(names) - set(expected))
    assert names == expected, (
        f"Tool names diverged from baseline: {len(missing)} missing, {len(added)} added.\n"
        f"Missing (first 10): {missing[:10]}\nAdded (first 10): {added[:10]}"
    )
