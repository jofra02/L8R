# Investigator Agent

> Verifies hypotheses by executing targeted tool calls guided by open questions.

## Overview

The Investigator agent (`src/agents/investigator.py`) is the primary tool execution node in the investigation loop. It selects the highest-priority active hypothesis and its related open questions, then uses the `ToolSelector` pipeline to identify and execute verification tools.

The agent builds rich context for tool selection including: ticket text, hypothesis details, active investigation question, existing facts, evidence summaries, topology, baselines, known changes, and path analysis. The `ToolSelector` operates in `"investigation"` mode, producing targeted tool selections with arguments.

Tool execution uses the `AdaptiveExecutor` for self-healing capabilities. When a tool fails due to missing dependencies (`MissingDependencyError`), the agent attempts in-flight recovery by selecting a resolution tool to fetch the missing information. If recovery fails, it creates a `PendingRequirement` that surfaces as a human-in-the-loop signal.

Evidence produced by each tool call is stored as an immutable snapshot via `EvidenceStore`, and the active open question (if any) is marked as answered with the evidence summary.

## When Called

Routed by supervisor when scoring returns `needs_more_evidence`, active hypotheses exist, and open questions are available (priority 11).

```python
if scoring and decision == "needs_more_evidence":
    active = [h for h in hypotheses if h.status in ("proposed", "verifying")]
    if active:
        open_count = len([q for q in open_questions if q.status == "open"])
        if open_count > 0:
            return "investigator_agent"
```

Also reached via fallback (priority 15) when active hypotheses and open questions exist but no scoring result yet.

Return: Fixed edge --> [Enricher](enricher.md) (sub-chain entry).

## Flow Diagram

```mermaid
flowchart TD
    A[hypotheses + open_questions] --> B[Select highest-priority active hypothesis]
    B --> C[Select active open question for target hypothesis]
    C --> D[Build ToolSelectionContext with full state]
    D --> E[ToolSelector: select tools - investigation mode]
    E --> F{Tools found?}
    F -- No --> G[Return empty]
    F -- Yes --> H[Auto-correct args against component IDs]
    H --> I[Sanitize tool arguments]
    I --> J[Safety + governance checks]
    J --> K[Execute via AdaptiveExecutor]
    K --> L{Success?}
    L -- Yes --> M[Save evidence snapshot]
    M --> N[Update hypothesis status to verifying]
    N --> O[Mark open question as answered]
    O --> P[Return evidence_refs + case_status=investigating]
    L -- MissingDependencyError --> Q[Attempt in-flight recovery]
    Q --> R{Recovery succeeded?}
    R -- Yes --> S[Save resolution evidence + return]
    R -- No --> T[Create PendingRequirement - HITL signal]
    L -- Other error --> U[Save failure evidence + return]
```

## Input / Output Contract

| Field | Type | Source |
|---|---|---|
| **Input** | | |
| `hypotheses` | `List[Hypothesis]` | Hypothesis agent |
| `open_questions` | `List[OpenQuestion]` | Investigation planner |
| `components` | `List[Component]` | Mapper agent |
| `ticket` | `Ticket` | Ingestion |
| `facts` | `Dict` | Enricher agent |
| `evidence_refs` | `List[EvidenceSnapshot]` | Previous collection passes |
| `topology_nodes` | `List[TopologyNode]` | Enricher agent |
| `topology_edges` | `List[TopologyEdge]` | Enricher agent |
| `client_context` | `ClientContext` | Context agent |
| `path_analysis` | `PathAnalysis` | Hypothesis agent |
| `customer_id` | `str` | Ingestion |
| **Output** | | |
| `hypotheses` | `List[Hypothesis]` | Updated (target set to `verifying`, evidence_refs appended) |
| `evidence_refs` | `List[EvidenceSnapshot]` | Appended with new snapshots |
| `open_questions` | `List[OpenQuestion]` | Active question marked `answered` |
| `pending_requirements` | `List[PendingRequirement]` | Created on unrecoverable missing dependencies |
| `case_status` | `str` | Set to `"investigating"` |

### Input Example

```json
{
  "hypotheses": [
    { "id": "h1", "summary": "NTP time skew exceeds Kerberos tolerance", "status": "verifying", "rank": 1, "evidence_refs": ["ev-001"] }
  ],
  "open_questions": [
    { "id": "q1", "question": "Is W32Time service running on DC-NORTH?", "status": "open", "source_hypothesis_id": "h1" }
  ],
  "components": [
    { "id": "dc-north", "ref": "DC-NORTH", "role": "server", "vendor": "microsoft" }
  ],
  "ticket": { "id": "INC-4012", "text": "Kerberos errors. DC-NORTH, ntp-pool.corp.local." },
  "facts": { "ntp_offset_dc_north": "+347 seconds" },
  "customer_id": "tenant_acme"
}
```

### Output Example

```json
{
  "evidence_refs": [
    {
      "id": "ev-002",
      "tool_call_id": "auto",
      "tool_name": "get_service_status",
      "tool_args": { "device": "dc-north", "service": "W32Time" },
      "timestamp": "2026-03-16T08:22:00Z",
      "content_hash": "sha256:d4e5f6...",
      "summary": "W32Time service is running but configured with wrong NTP peer (local CMOS clock)",
      "storage_ref": "evidence/tenant_acme/ev-002.json"
    }
  ],
  "hypotheses": [
    { "id": "h1", "status": "verifying", "evidence_refs": ["ev-001", "ev-002"] }
  ],
  "open_questions": [
    { "id": "q1", "status": "answered", "answer": "W32Time is running but misconfigured — using local CMOS clock instead of ntp-pool.corp.local" }
  ],
  "case_status": "investigating"
}
```

### Where Output Goes

`evidence_refs` (appended) flow directly to the [Enricher](enricher.md) via the fixed sub-chain edge for fact and topology extraction. `open_questions` (with updated status) are read by the [Scoring Agent](scoring.md) for question completion ratio and by the [Investigation Planner](investigation_planner.md) to decide whether to generate new questions.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LLM_MODEL_INVESTIGATOR` | `gpt-5.2` | LLM profile for tool selection context |
| `MCP_SERVER_TIMEOUT` | `30` | Timeout for MCP tool execution |
| `SAFETY_BLOCKED_KEYWORDS` | (list) | Keywords that block unsafe tool execution |

## Key Implementation Details

- Hypothesis selection priority: `verifying` status first, then by `rank` (ascending).
- Open question selection: prefers questions linked to target hypothesis via `source_hypothesis_id`; falls back to any open question.
- Uses centralized `ToolSelector` in `"investigation"` mode with `max_intents=2`, `max_tools=3`.
- Argument auto-correction: matches LLM-generated argument values against known component IDs by `id`, `ref`, or `role`.
- Smart argument sanitization via `sanitize_tool_args`: distinguishes executor roles (firewall, router, switch, loadbalancer, gateway, server, host, hypervisor, appliance, controller) from target roles (subnet, endpoint, url, dns_name, user, network, vm, container, pod). Executors map to `device` param; targets map to `target` param.
- Safety check via `is_safe_tool` blocks execution of tools matching blocked keywords.
- Governance check via `is_tool_allowed_for_tenant` enforces per-tenant tool access control.
- `AdaptiveExecutor` provides retry logic and self-healing with context-aware error recovery.
- `MissingDependencyError` triggers an in-flight recovery loop: the agent selects a resolution tool from the registry to fetch the missing information before falling back to `PendingRequirement`.
- All evidence (success, failure, recovery) is stored via `EvidenceStore` as immutable, tenant-scoped snapshots.
- Evidence snapshots are linked to hypotheses via `hypothesis.evidence_refs`.

## See Also

- [Investigation Planner](investigation_planner.md) -- produces the open questions consumed here
- [Enricher Agent](enricher.md) -- processes evidence produced by this agent
- [Adaptive Execution](../architecture/adaptive_execution.md) -- self-healing execution architecture
