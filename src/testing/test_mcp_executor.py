"""execute_mcp_tool: shared guardrail pipeline (no DB, no network).

Covers the extracted MCP execution helper used by both the Engineer agent and
the assessment Collection Engine: tenant injection, read-only allowlist,
preflight blocks, timeout handling and error classification.

Run: uv run pytest src/testing/test_mcp_executor.py
"""

import asyncio

import src.core.registry as registry_mod
import src.core.safety as safety
from src.core.mcp_executor import (
    execute_mcp_tool,
    is_read_only_tool_name,
)


class FakeWrapper:
    def __init__(self, result="ok", exc=None, delay_s=0.0):
        self.calls = []
        self._result = result
        self._exc = exc
        self._delay_s = delay_s

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._exc:
            raise self._exc
        return self._result


async def _patch_collaborators(monkeypatch, fake, *, safe=True, allowed=True):
    monkeypatch.setattr(safety, "is_safe_tool", lambda name, args: safe)

    async def governance(name, cid):
        return allowed

    monkeypatch.setattr(safety, "is_tool_allowed_for_tenant", governance)
    monkeypatch.setattr(
        registry_mod.CapabilityRegistry, "get_tool", classmethod(lambda cls, name: fake)
    )


# ---------------------------------------------------------------------------
# Read-only allowlist
# ---------------------------------------------------------------------------

def test_read_only_allowlist_names():
    assert is_read_only_tool_name("fgt_cmdb_sys_get_admin")
    assert is_read_only_tool_name("fgt_monitor_sys_get_status")
    # No GET marker
    assert not is_read_only_tool_name("fgt_cmdb_sys_admin")
    # Mutating / active markers
    assert not is_read_only_tool_name("fgt_cmdb_fw_ipmacbinding_setting_put_firewall_policy_policyid")
    assert not is_read_only_tool_name("fgt_cmdb_fw_ipmacbinding_setting_post_firewall_policy")
    assert not is_read_only_tool_name("fgt_cmdb_fw_ipmacbinding_setting_delete_firewall_policy_policyid")
    assert not is_read_only_tool_name("fgt_monitor_sys_post_vmlicense_download")


async def test_enforce_read_only_blocks_mutating_tool(monkeypatch):
    fake = FakeWrapper()
    await _patch_collaborators(monkeypatch, fake)

    res = await execute_mcp_tool(
        "fgt_cmdb_x_put_thing", {"device": "fw1"}, "acme", enforce_read_only=True
    )
    assert not res.ok
    assert res.error_type == "read_only"
    assert res.preflight_failure
    assert not fake.calls, "mutating tool must never reach the gateway"


async def test_enforce_read_only_allows_get_tool(monkeypatch):
    fake = FakeWrapper(result={"results": []})
    await _patch_collaborators(monkeypatch, fake)

    res = await execute_mcp_tool(
        "fgt_cmdb_sys_get_admin", {"device": "fw1"}, "acme", enforce_read_only=True
    )
    assert res.ok
    assert res.content == {"results": []}


# ---------------------------------------------------------------------------
# Preflight blocks
# ---------------------------------------------------------------------------

async def test_safety_block(monkeypatch):
    fake = FakeWrapper()
    await _patch_collaborators(monkeypatch, fake, safe=False)

    res = await execute_mcp_tool("fgt_x_get_y", {}, "acme")
    assert not res.ok and res.error_type == "safety" and res.preflight_failure
    assert not fake.calls


async def test_tenant_governance_block(monkeypatch):
    fake = FakeWrapper()
    await _patch_collaborators(monkeypatch, fake, allowed=False)

    res = await execute_mcp_tool("fgt_x_get_y", {}, "acme")
    assert not res.ok and res.error_type == "authorization" and res.preflight_failure
    assert not fake.calls


async def test_tool_not_found(monkeypatch):
    await _patch_collaborators(monkeypatch, None)

    res = await execute_mcp_tool("missing_get_tool", {}, "acme")
    assert not res.ok and res.error_type == "not_found" and res.preflight_failure


# ---------------------------------------------------------------------------
# Tenant injection
# ---------------------------------------------------------------------------

async def test_tenant_injected_and_overrides_caller_value(monkeypatch):
    fake = FakeWrapper()
    await _patch_collaborators(monkeypatch, fake)

    args = {"device": "fw1", "tenant": "victim_tenant"}
    res = await execute_mcp_tool("fgt_x_get_y", args, "acme")

    assert res.ok
    assert fake.calls[0]["tenant"] == "acme"
    assert fake.calls[0]["device"] == "fw1"
    assert res.final_args["tenant"] == "acme"
    # Caller's dict is never mutated
    assert args["tenant"] == "victim_tenant"


# ---------------------------------------------------------------------------
# Execution failures
# ---------------------------------------------------------------------------

async def test_timeout_classification(monkeypatch):
    fake = FakeWrapper(delay_s=0.5)
    await _patch_collaborators(monkeypatch, fake)

    res = await execute_mcp_tool("fgt_x_get_y", {}, "acme", timeout_s=0.05)
    assert not res.ok
    assert res.error_type == "timeout"
    assert res.stage == "execute" and not res.preflight_failure


async def test_connection_error_classification(monkeypatch):
    fake = FakeWrapper(exc=ConnectionError("connection refused"))
    await _patch_collaborators(monkeypatch, fake)

    res = await execute_mcp_tool("fgt_x_get_y", {}, "acme")
    assert not res.ok and res.error_type == "connection"


async def test_unknown_error_classification(monkeypatch):
    fake = FakeWrapper(exc=RuntimeError("boom"))
    await _patch_collaborators(monkeypatch, fake)

    res = await execute_mcp_tool("fgt_x_get_y", {}, "acme")
    assert not res.ok and res.error_type == "unknown"
    assert "boom" in res.error


# ---------------------------------------------------------------------------
# Gateway-reported errors (transport ok, isError payload)
# ---------------------------------------------------------------------------

async def test_gateway_error_flag(monkeypatch):
    fake = FakeWrapper(result="Error: device 'fw9' not found")
    await _patch_collaborators(monkeypatch, fake)

    res = await execute_mcp_tool("fgt_x_get_y", {}, "acme")
    assert res.ok  # the call itself succeeded
    assert res.gateway_error
