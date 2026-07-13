# Skill: Lateral Thinking — Investigation Re-framing

## Purpose

Structured techniques to escape a stalled investigation. Domain-agnostic: applies to networking, cloud, database, application, security, or any IT domain.

Load this skill when any of these is true:

- Two consecutive tool calls produced **no new facts**.
- The evidence **contradicts every open hypothesis**, or two collected facts contradict each other.
- The symptom looks **"impossible"** given the configuration you have verified.
- `search_tool_catalog` keeps returning nothing relevant for how you are phrasing the need.
- You are about to declare the case blocked.

## Core Rule

A pivot is only valid if it ends in a **new testable question answerable by a read-only tool call**. Re-framing that does not change what you will query next is rumination, not lateral thinking. After each technique, write down: *new question → evidence that would answer it → tool to get that evidence*.

## Techniques

### 1. Assumption audit
List every assumption the current dead end rests on ("the device is the right device", "the report describes the real symptom", "this config is the effective config", "the clock is right", "the object name means what it suggests"). Test the **cheapest unverified** one first. Most stalls are a false assumption, not missing data.

### 2. Question inversion
Stop asking "why is X failing?" and ask "**what would have to be true for X to behave exactly this way?**" Enumerate the conditions; each condition is a checkable fact. This converts a mystery into a checklist.

### 3. Altitude shift
Move between instance ↔ class ↔ system. One user failing → is the whole group failing? One tunnel down → are all tunnels on that interface down? A class-level answer instantly changes the failure domain and often the responsible object.

### 4. Adjacency pivot
Interrogate the **neighbors** of the failing object from the situation model: upstream dependency, downstream consumer, sibling behind the same control point. If the neighbor shows the same anomaly, the problem is in the shared element, not the reported one.

### 5. Time pivot
Shift from "what is wrong" to "**what changed**". Correlate the symptom's onset with known changes, expiries, renewals, reboots, and scheduled jobs from the tenant context. A symptom with a start time is a change until proven otherwise.

### 6. Negative space
Ask what is **absent that should exist**: the missing log entry, the missing session, the missing route, the missing lease. Absence localizes the failure earlier in the chain than any error message — traffic that never generated a log never reached the logging point.

### 7. Vocabulary pivot (catalog re-search)
When tool searches return junk, the failure is often lexical, not semantic. Re-search describing:
- the **effect** instead of the mechanism ("clients cannot resolve names" → "DNS server configuration", "DNS proxy statistics"),
- the **generic term** instead of the vendor term, and vice versa,
- the **data** you want instead of the action ("list of active sessions with source and destination" instead of "check traffic").

### 8. Layer shift
Deliberately move one layer down (application → transport → network → physical) or one layer up. Verify the layer **below** the one where the symptom is reported before elaborating theories at the reported layer.

### 9. Path bisection
When the failing path is long, pick a probe point near the middle and determine on which side the anomaly lies. Each read-only query should cut the remaining search space roughly in half — choose queries by information gained, not by convenience.

### 10. Contradiction interrogation
When two facts conflict, do not discard one — ask **in which context each measurement was true**: different scope (VDOM/VRF/namespace/tenant), different time window, different vantage point, cached versus live data. The reconciliation of a contradiction is usually the diagnosis.

### 11. Reporter reframe
Treat the ticket wording as testimony, not ground truth. The reporter describes an experience, not a cause; the real fault may sit in a system they never mentioned. Re-derive the symptom from raw evidence and check whether the reported object is even on the failing path.

## Bounds

- Apply **one technique at a time**; let its result choose the next.
- After **three sterile pivots** (no new facts), stop: the honest output is an escalation. Report what was **ruled out** — negative findings backed by evidence are a valid, valuable result. Set `case_status` accordingly (`needs_human` or `blocked`) per the base methodology.
- All platform rules stay in force: read-only, evidence-only, configuration-first, tenant-scoped. Lateral means *sideways in hypothesis space*, never outside the guardrails.

## Integration with the Base Loop

This skill plugs into Phase 4 (Reasoning Loop) steps 13–14 — it is the structured version of "step back and choose a different next question". It does not replace the Output Contract: pivots you took and discarded belong in **Remaining Uncertainty** / **Limitations**, not in the main narrative.
