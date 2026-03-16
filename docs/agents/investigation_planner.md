# Investigation Planner Agent

> Generates structured open questions to drive targeted investigation of active hypotheses.

## Overview

The Investigation Planner (`src/agents/investigation_planner.py`) bridges hypothesis generation and evidence gathering. Rather than allowing the Investigator to gather evidence ad-hoc, this agent produces a prioritized list of `OpenQuestion` objects that specify exactly what needs to be answered, why it matters, and what constitutes a complete answer.

Each question is linked to a source hypothesis via `source_hypothesis_id` and includes dependency ordering (`depends_on`) so that prerequisite questions are answered first. The `done_when` field provides a concrete, verifiable completion criterion.

The agent is re-entrant. If open questions from a prior iteration remain unanswered, it skips re-planning to avoid discarding in-progress work. When all prior questions have been answered, it generates a fresh batch incorporating the new knowledge. Previously answered questions are preserved in state for audit and context.

## When Called

Routed by supervisor when scoring returns `needs_more_evidence`, active hypotheses exist, but no open questions remain (priority 10).

```python
if scoring and decision == "needs_more_evidence":
    active = [h for h in hypotheses if h.status in ("proposed", "verifying")]
    if active:
        open_count = len([q for q in open_questions if q.status == "open"])
        if open_count == 0:
            return "investigation_planner"
```

Also reached via fallback (priority 14) when active hypotheses exist but no open questions and no scoring yet.

Return: Fixed edge → supervisor.

## Flow Diagram

```mermaid
flowchart TD
    A[hypotheses + facts + evidence_refs] --> B{Any hypotheses?}
    B -- No --> C[Return case_status=modeled]
    B -- Yes --> D{Open questions remain?}
    D -- Yes --> E[Skip re-plan, return case_status=planned]
    D -- No --> F[Build context: facts, evidence, path_analysis, answered questions]
    F --> G[LLM: Generate 2-6 open questions]
    G --> H[Merge: preserve answered + add new open questions]
    H --> I[Return open_questions + case_status=planned]
```

## Input / Output Contract

| Field | Type | Source |
|---|---|---|
| **Input** | | |
| `hypotheses` | `List[Hypothesis]` | Hypothesis agent |
| `facts` | `Dict` | Enricher agent |
| `evidence_refs` | `List[EvidenceSnapshot]` | Evidence collector / Investigator |
| `structured_facts` | `List[Fact]` | Enricher agent |
| `open_questions` | `List[OpenQuestion]` | Previous iteration |
| `path_analysis` | `PathAnalysis` | Hypothesis agent |
| `ticket` | `Ticket` | Ingestion |
| **Output** | | |
| `open_questions` | `List[OpenQuestion]` | Merged list (answered preserved + new open) |
| `case_status` | `str` | Set to `"planned"` |

### Input Example

```json
{
  "hypotheses": [
    { "id": "h1", "summary": "NTP time skew on DC-NORTH exceeds Kerberos tolerance", "status": "proposed", "rank": 1 }
  ],
  "facts": { "ntp_offset_dc_north": "+347 seconds" },
  "evidence_refs": [
    { "id": "ev-001", "tool_name": "get_ntp_status", "summary": "NTP offset +347s on DC-NORTH" }
  ],
  "ticket": { "id": "INC-4012", "mode": "incident" }
}
```

### Output Example

```json
{
  "open_questions": [
    {
      "id": "q1",
      "question": "Is the Windows Time (W32Time) service running and configured correctly on DC-NORTH?",
      "why": "A misconfigured or stopped time service would explain the 347-second drift from the NTP source",
      "depends_on": [],
      "done_when": "W32Time service status and NTP peer configuration retrieved from DC-NORTH",
      "status": "open",
      "source_hypothesis_id": "h1"
    },
    {
      "id": "q2",
      "question": "What is the current Kerberos maximum clock skew tolerance configured on the domain?",
      "why": "Confirms whether the observed 347-second offset exceeds the policy threshold",
      "depends_on": [],
      "done_when": "Kerberos policy MaxClockSkew value retrieved",
      "status": "open",
      "source_hypothesis_id": "h1"
    }
  ],
  "case_status": "planned"
}
```

### Where Output Goes

`open_questions` are consumed by the [Investigator](investigator.md) (selects questions to drive tool execution), [Scoring Agent](scoring.md) (question completion ratio in confidence calculation), and the [Supervisor](supervisor.md) (routes to investigator when open questions exist, or back to investigation_planner when all are answered).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LLM_MODEL_HYPOTHESIS` | `gpt-5.2` | Shared LLM profile (via `investigation_planner` agent key) |

## Key Implementation Details

- Uses `PydanticOutputParser` with `OpenQuestionList` schema for structured output.
- LLM temperature set to `0.0` for deterministic question generation.
- Generates 2-6 questions per planning pass targeting active (proposed/verifying) hypotheses.
- Each `OpenQuestion` contains: `id`, `question`, `why`, `depends_on` (list of question IDs), `done_when`, `status`, `source_hypothesis_id`, `answer`.
- Question statuses: `open`, `answered`, `irrelevant`.
- Merge strategy: preserves questions with status `answered` or `irrelevant` from prior iterations; replaces all `open` questions with the new plan.
- Questions are ordered by diagnostic value -- the most discriminating questions appear first.
- All questions must be answerable by read-only tool execution (configuration checks, status queries, log inspections).
- Context includes: formatted facts, hypothesis summaries, evidence summaries (max 10), path analysis, and previously answered questions with their answers.

## See Also

- [Investigator Agent](investigator.md) -- consumes open questions to guide tool execution
- [Hypothesis Agent](hypothesis.md) -- produces the hypotheses that drive question generation
- [Scoring Agent](scoring.md) -- evaluates progress after investigation cycles
