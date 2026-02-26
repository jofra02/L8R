from src.core.models import GlobalState, Ticket, Classification, Component, EvidenceSnapshot, Hypothesis
from typing import List, Dict, Any
from datetime import datetime

def mock_ticket(text: str = "Test ticket", id: str = "TICKET-001") -> Ticket:
    return Ticket(
        id=id,
        text=text,
        source="email",
        created_at=datetime.now(),
        mode="incident",
        severity="medium"
    )

def mock_classification(domains: List[str] = ["network"]) -> Classification:
    return Classification(
        domains=domains,
        confidence=0.9,
        rationale="Mock logic"
    )

def mock_component(id: str, role: str) -> Component:
    return Component(
        id=id,
        name=id,
        role=role,
        vendor="Fortinet",
        ref=f"10.0.0.{id[-1]}"
    )

def mock_evidence(tool_name: str, content: str) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        id=f"ev-{tool_name}",
        run_id="run-1",
        tool_call_id="call-1",
        tool_name=tool_name,
        tool_args={},
        timestamp=datetime.now(),
        content_hash="hash123",
        content=content, # Note: Content is NOT a field in EvidenceSnapshot model, it's stored in DB. But for this agent test we might need to adjust if the agent reads it from somewhere else. 
        # Wait, the Response agent reads from 'summary'. The 'content' arg in this mock seems unused by the model but used by the factory.
        # Let's check the model definition again. EvidenceSnapshot has 'summary' and 'storage_ref'.
        # The 'content' isn't in the model.
        # But wait, the previous error said 'content_hash' missing.
        summary=f"Summary of {tool_name}: {content}",
        storage_ref=f"/tmp/{tool_name}.log"
    )

def get_base_state() -> GlobalState:
    """Returns a minimal valid state."""
    return {
        "ticket": mock_ticket(),
        "meta": {"iteration": 1, "start_time": datetime.now().isoformat()},
        "messages": [],
        "classification": mock_classification(),
        "components": [],
        "evidence_refs": [],
        "facts": {},
        "hypotheses": [],
        "plan": None,
        "classification_needed": False,
        "response_needed": False
    }

def get_response_ready_state() -> GlobalState:
    """State ready for Response Agent testing."""
    state = get_base_state()
    state["components"] = [mock_component("fgt_demo", "firewall")]
    state["evidence_refs"] = [
        mock_evidence("get_system_status", "Version: 7.0.0"),
        mock_evidence("fgt_monitor_sys_get_status", "Host unreachable")
    ]
    state["hypotheses"] = [
        Hypothesis(id="h1", summary="Firewall rule blocking traffic", status="verified", rank=1, confidence=0.8, reasoning="Tool check failed")
    ]
    state["facts"] = {"fw_version": "7.0.0"}
    return state
