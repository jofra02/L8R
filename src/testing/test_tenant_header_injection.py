"""execute_tool injects the tenant selector framework-side (no DB, no network).

The gateway routes each call against the tenant whose header it receives. The
app must supply that tenant from the run context (customer_id), NOT from the
LLM — even if the model omits it or supplies a wrong value, our injection wins.

Run: uv run pytest src/testing/test_tenant_header_injection.py
"""

import src.core.registry as registry_mod
import src.core.safety as safety
from src.agents.engineer_tools import create_engineer_tools


class FakeWrapper:
    """Records the kwargs a gateway tool is invoked with, then short-circuits
    before the evidence-store path."""

    def __init__(self):
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError("stop-before-evidence")


def _get_execute_tool(tools):
    return next(t for t in tools if t.name == "execute_tool")


async def _patch_collaborators(monkeypatch, fake):
    monkeypatch.setattr(safety, "is_safe_tool", lambda name, args: True)

    async def allow(name, cid):
        return True

    monkeypatch.setattr(safety, "is_tool_allowed_for_tenant", allow)
    monkeypatch.setattr(
        registry_mod.CapabilityRegistry, "get_tool", classmethod(lambda cls, name: fake)
    )


async def test_injects_tenant_when_llm_omits_it(monkeypatch):
    fake = FakeWrapper()
    await _patch_collaborators(monkeypatch, fake)

    tools, _ = create_engineer_tools(customer_id="druidics", run_id="r", ticket_id="t")
    await _get_execute_tool(tools).ainvoke(
        {"tool_name": "fgt74_x", "tool_params": '{"device": "fw1"}'}
    )

    assert fake.calls, "gateway tool was not invoked"
    assert fake.calls[0]["tenant"] == "druidics"
    assert fake.calls[0]["device"] == "fw1"


async def test_injection_overrides_llm_supplied_tenant(monkeypatch):
    fake = FakeWrapper()
    await _patch_collaborators(monkeypatch, fake)

    tools, _ = create_engineer_tools(customer_id="druidics", run_id="r", ticket_id="t")
    # The model tries to spoof another tenant — the framework must override it.
    await _get_execute_tool(tools).ainvoke(
        {"tool_name": "fgt74_x", "tool_params": '{"device": "fw1", "tenant": "victim_tenant"}'}
    )

    assert fake.calls[0]["tenant"] == "druidics"
