# Response Agent

## Description
The Response Agent is the final node in the graph. It compiles all the work done (hypotheses, evidence, plan) into a coherent Technical Report and a "Handoff Package" for the human operator or external system. It also handles HITL pause scenarios when pending requirements exist.

## Role in Graph
- **Node Name:** `response_agent`
- **Upstream:** `supervisor` (when finishing) or `planner_agent`.
- **Downstream:** `END` (Terminates the graph execution).

## Inputs
- `state["ticket"]`: Ticket details.
- `state["hypotheses"]`: Final list of hypotheses.
- `state["plan"]`: Generated plan.
- `state["evidence_refs"]`: All collected evidence.
- `state["facts"]`: Collected facts.
- `state["pending_requirements"]`: (optional) Blocking requirements for HITL pause.

## Outputs
- `state["final_answer"]`: A markdown report string.
- `state["handoff"]`: A `HandoffPackage` containing artifact paths and escalation recommendations.

## HITL Pause Handling
When `pending_requirements` exist, the agent:
1. Dumps user-friendly requirements to `data/needs.json`.
2. Saves full state checkpoint to `data/paused_state.json` for resume capability.
3. Returns a structured "Action Required" message with instructions for the operator.
4. Skips LLM synthesis entirely.

## Prompts

### Final Report Generation
**System:** "IT Support / Incident & Change Engineer"
**Mission:** Resolve problems, validate configurations, and assess IT system states objectively and verifiably.

**Contract:**
1. Conclusion (validation result or root cause diagnosis).
2. Evidence (supporting data, what was checked).
3. Plan / Remediation / Blockers (only if applicable).

**Rules:**
- Evidence-only: do not invent anything or assume something is broken if the ticket only asks for validation.
- Be concise and direct.
- Prioritize the directly useful conclusion.

**Output Format (Markdown):**
1. **Conclusion / Primary Diagnosis** — confirmed root cause or validated state.
2. **Brief Context** — ticket objective + scope (1-2 lines).
3. **Key Evidence and Tools Executed** — concise grouped list.
4. **Next Steps (Action / Remediation / Blockers)** — what to do next or "No action required."

## Key Logic & Interactions
- **LLM Model:** Uses `LLM_MODEL_RESPONSE` (e.g., `gpt-5-mini`) — synthesis and formatting, no deep reasoning needed.
- **Domain-Agnostic:** The report prompt is technology-neutral — no bias toward any specific IT domain.
- **Handoff Package:** Includes evidence artifact paths and recommended escalation team/reason.
- **State Serialization:** Custom `StateEncoder` handles datetime, UUID, and Pydantic model serialization for checkpoint dumps.
