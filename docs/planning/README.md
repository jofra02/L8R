# Planning

Active plans and design source material only. A design spec lives here while the work is pending; once implemented (or abandoned) it moves to [`../legacy/planning/`](../legacy/planning/) with a header note pointing at the docs that superseded it.

## Contents

| Item | Purpose |
|---|---|
| [roadmap.md](roadmap.md) | Planned work not yet scheduled — each item gets its own design doc here before implementation |
| `assessment/` | Source material for the Device Assessment module: `fortigate_hardening_manual.txt` (control source for the `security-baseline` definition) and `requirements.txt` (original module requirements, in Spanish) |

**Do not move or rename `assessment/fortigate_hardening_manual.txt`** — the path is referenced from the assessment definition YAMLs (`src/assessments/definitions/fortinet/fortigate/security-baseline/*.yaml`), which are immutable per version (content-hash guarded).

## Archived specs

Implemented design specs formerly in this folder now live in `../legacy/planning/`: `minimal_agent_redesign.md` (Engineer ReAct architecture), `skills_implementation.md`, `data_layer_blueprint.md`, `model_governance.md`, `onboarding_plan.md`, and the two pre-implementation skill drafts (`skill_draft_*.md`).
