# Skill Authoring Guide

How to write investigation skills for the Engineer agent. The canonical style
reference is the base skill: `src/agents/skills/base_investigation.md`.

## Canonical Format

Every skill follows this shape:

```markdown
# Skill: <Name>

<One line stating what the skill resolves and how.>

1. <Imperative step — one idea per line.>
2. <...>
n. <Closing step: how the investigation is bounded or concluded.>

<Optional trigger block: when to load another skill or stop.>

<Optional reasoning-format line.>
```

Rules:

- **Title**: `# Skill: <Name>`. No other top-level heading.
- **Purpose**: exactly one line. If it takes a paragraph to explain, the skill
  is doing too much — split it.
- **Steps**: numbered, imperative, concise. One idea per line. No sub-bullets
  unless strictly necessary. Order them as the engineer should execute them.
- **Triggers/bounds**: short prose blocks after the steps. State when to load
  another skill (`load_domain_skill("...")`), when to stop, and any safety
  rails. See `lateral_thinking.md` (Bounds section) and
  `fortigate_licensing.md` (safety rail against mutating license tools).
- **Reasoning format line** (optional, for methodology skills): a single bold
  arrow chain, e.g.
  `**Facts → Model → Hypotheses → Test → Result → Implication → Next step**`.
- No encyclopedic sections, no phase hierarchies, no long principle catalogs.
  The skill is injected into a working context — every line costs tokens on
  every run it is loaded.

## Abstraction Rule

- The **base skill** uses only abstract engineering concepts (scope, state,
  effective state, dependency, boundary, evidence, failure domain). It must
  never name a technology, protocol, vendor, or product category — examples
  narrow the investigation space.
- **Domain skills** do the opposite: they anchor concrete vendor terms, exact
  tool names, and platform-specific pitfalls. That is their value.

## Tool Anchor Contract

Domain skills may reference exact gateway tool names so the Engineer can
execute them without a catalog hit ("search is discovery, not permission"):

- Write anchors in backticks: `` `fgt74_monitor_system_status_get` ``.
- A trailing `*` marks a prefix family: `` `fgt74_cmdb_registration_post_forticare_*` ``.
- Every anchor must exist in `mcp_gateway/baseline_tools.txt`. Verify against
  the Qdrant `tool_catalog` too — an anchor filtered out by the safety
  keywords is executable-looking but blocked.
- Never anchor mutating tools (update/upload/create/upgrade/download actions
  that change device state), even if the safety filter currently misses them.

`src/testing/test_skill_drift.py` pins this contract: it fails if an anchor
disappears from the baseline or if `DOMAIN_SKILL_MAP` points to a missing file.

## Registration

1. Put the skill file in `src/agents/skills/<name>.md`. Any `.md` in that
   directory (except `base_investigation.md`) is listed as an available
   domain — do not put templates or drafts there.
2. Map trigger keywords to the filename in `DOMAIN_SKILL_MAP`
   (`src/agents/engineer_tools.py`). Add every term a model plausibly uses
   for the domain (singular/plural, vendor names, symptom words) — the map is
   an exact-match funnel, and misses cost an entire investigation branch.

## Checklist

1. Write the skill in the canonical format.
2. Verify every tool anchor against `mcp_gateway/baseline_tools.txt`.
3. Register keywords in `DOMAIN_SKILL_MAP`.
4. `uv run pytest src/testing/test_skill_drift.py`
5. Smoke test: run a real ticket through the API that should trigger the
   skill; confirm the Engineer loads it and the anchors execute.
