"""Log-retrieval discoverability enrichment test.

The support_ai_agent tool catalog embeds only tool descriptions (never names),
and the local-disk log retrieval tools do not even contain the word "log" in
their names (fgt_cmdb_disk_get_*). The enrich_log_retrieval vendor hook
appends storage/vocabulary context to the retrieval and device-state
summaries so semantic search can surface them. This test builds the gateway
offline and asserts the enrichment landed on every backend family equally.
"""

import asyncio

# One retrieval tool per backend family — all four must be enriched alike.
RETRIEVAL_TOOLS = [
    "fgt_cmdb_disk_get_type",
    "fgt_log_mem_get_memory_type",
    "fgt_cmdb_faz_get_fortianalyzer_type",
    "fgt_cmdb_fcloud_get_forticloud_type",
]

DEVICE_STATE_TOOL = "fgt_cmdb_log_get_device_state"


def test_log_retrieval_descriptions_enriched():
    from gateway.app import build_gateway

    gateway = build_gateway()
    tools = asyncio.run(gateway.get_tools())

    for name in RETRIEVAL_TOOLS:
        description = tools[name].description or ""
        assert "web browsing history" in description, (
            f"{name}: retrieval vocabulary append missing from description"
        )
        assert "stored" in description, (
            f"{name}: storage backend label missing from description"
        )

    state_description = tools[DEVICE_STATE_TOOL].description or ""
    assert "log storage backends" in state_description, (
        f"{DEVICE_STATE_TOOL}: device-state vocabulary append missing"
    )
