> Historical skill draft — this content shipped as `src/agents/skills/networking.md`. Kept for reference only.

# Skill: Network Engineering Investigation Methodology

## Purpose

This skill defines HOW a network engineer agent must investigate network-related requests using real evidence from the current environment.

Its purpose is not to memorize vendor commands, repeat fixed troubleshooting recipes, or assume a specific implementation model. Its purpose is to enforce a disciplined network investigation method that works across different platforms, topologies, control models, and operational contexts.

The agent must not infer topology, forwarding behavior, object identity, protocol role, or root cause from ticket wording alone. It must discover the network context, determine the relevant network domain, verify actual state, and only then conclude, recommend, or change anything.

---

## Core Rule

**Never infer network behavior from intent, configuration wording, or familiar patterns. Discover the effective behavior first.**

A request may describe symptoms, expectations, or user interpretation. It is not authoritative evidence of forwarding behavior, adjacency, reachability, path selection, policy effect, state convergence, or causality.

---

## Authoring Rule for This Skill

**Use broad networking concepts, not partial lists of implementations or feature subsets.**

When describing what to investigate, prefer network domains and effective-state concepts over enumerating selected protocols, mechanisms, or product features.

Prefer terms such as:
- network path
- forwarding decision
- forwarding state
- control-plane state
- data-plane state
- adjacency
- reachability
- topology boundary
- segmentation boundary
- encapsulation
- translation
- transformation
- selection logic
- policy effect
- dependency chain
- symmetry
- convergence
- propagation
- operational state
- effective behavior
- evidence

Avoid:
- defining a network domain through a partial list of protocols
- equating networking with only routing or only firewalling
- treating one feature family as the source of truth for all cases
- embedding examples that silently exclude valid network designs
- assuming a specific vendor mental model

This skill defines method for network investigation, not a closed taxonomy of network technologies.

---

## Universal Network Investigation Principles

1. **Discover before reasoning**
   - Do not reason about path, reachability, or causality until you verify what actually exists.

2. **Scope before drill-down**
   - Resolve the relevant network boundary before deep inspection.

3. **Effective behavior before explanation**
   - Establish what the network is actually doing before explaining why.

4. **Control-plane state and data-plane behavior are not the same**
   - A learned state does not guarantee usable forwarding.
   - A configured object does not guarantee it is taking effect.

5. **The named object may not be the causal object**
   - The reported interface, device, tunnel, subnet, or policy may only be where the symptom is visible.

6. **Forward and return behavior must both be considered**
   - A usable forward path alone does not prove bidirectional success.

7. **Dependencies must be checked across domains**
   - Apparent issues in one network function may originate in another.

8. **Every conclusion must be backed by network evidence**
   - Findings must come from observed state, counters, adjacency, resolution, lookup results, session evidence, propagation state, or equivalent proof.

9. **The next step must follow the previous evidence**
   - The agent must adapt the investigation as new state is discovered.

10. **Do not confuse absence of evidence with evidence of absence**
   - Missing telemetry, missing counters, or missing visibility must be treated explicitly.

---

## Investigation Modes

Before using tools, determine the request mode.

### Incident
Something is failing, degraded, unstable, inconsistent, or behaving unexpectedly.

Goal:
- determine expected network behavior
- determine observed network behavior
- identify the divergence
- explain the divergence with evidence

### Change Request
Something must be introduced, modified, removed, redirected, enabled, disabled, or restructured in the network.

Goal:
- determine desired end state
- determine current network state and dependencies
- determine the minimal valid network change
- evaluate risk, validation, and rollback

### Review
The user wants assessment, validation, health review, consistency review, design review, or posture review.

Goal:
- inventory the relevant network scope
- evaluate current condition
- identify findings
- prioritize actions

### Inquiry
The user wants verified information about the network environment.

Goal:
- resolve scope
- query authoritative sources
- return a direct evidence-based answer

---

## Phase 1: Resolve Scope

Before detailed investigation, resolve the minimum scope necessary.

### Minimum scope

1. **Target**
   - What device, path, segment, service edge, traffic class, topology area, or logical boundary is in scope?

2. **Context**
   - What site, tenant, environment, role, plane, or management boundary applies?

3. **Intent**
   - What exactly is the user asking to know, validate, fix, or change?

4. **Traffic context**
   - What communicating endpoints, selectors, prefixes, services, flows, or classes of traffic are relevant?

5. **Constraint**
   - Is the task read-only, diagnostic, advisory, validation-only, or implementation-oriented?

6. **Confidence boundary**
   - What is known, what is assumed, and what still must be verified?

If scope is incomplete, the agent must begin by discovering the network context rather than filling gaps with assumptions.

---

## Phase 2: Build the Network Situation Model

Before drilling into specifics, construct a minimal model of the network situation relevant to the request.

### Resolve and collect

1. **Identity**
   - What network objects are actually involved?

2. **Topology boundary**
   - Where does the relevant network path begin and end?
   - Which devices, links, domains, or logical boundaries participate?

3. **Current operational state**
   - What is actually up, down, degraded, inactive, inconsistent, or transitional?

4. **Expected behavior**
   - What should the network do if it is behaving correctly?

5. **Effective behavior**
   - What path, policy effect, transformation, or treatment is actually happening now?

6. **Dependency chain**
   - What supporting elements must function for the target behavior to succeed?

7. **State distribution**
   - Is the relevant state local, learned, propagated, synchronized, programmed, or inferred?

8. **Change indicators**
   - What recent transitions, failovers, flaps, updates, or state changes may explain the condition?

9. **Available evidence sources**
   - Which sources are authoritative for topology, control-plane state, data-plane state, and real-time behavior?

The agent must build only the model required to explain the request correctly.

---

## Phase 3: Network Investigation Lenses

Investigate through broad networking lenses, not through protocol-specific checklists.

### A. Forwarding Lens
Determine how the network is actually deciding where traffic goes.

Questions:
- What is the effective forwarding decision for the traffic in question?
- Which lookup, selection, or path decision is taking effect?
- Is the observed forwarding behavior the expected one?
- Is the selected path actually usable?

### B. Adjacency and Reachability Lens
Determine whether the network can actually reach the next required point in the path.

Questions:
- Is local or remote adjacency established where required?
- Is the next dependency reachable from the current point?
- Is there evidence of incomplete resolution or broken reachability?
- Is the failure local, near-end, far-end, or path-intermediate?

### C. Topology and Boundary Lens
Determine where the traffic or failure domain lives.

Questions:
- Which boundaries does the traffic cross?
- Where does the relevant network responsibility change?
- What is inside the investigated path and what is outside it?
- Is the issue isolated, shared, or boundary-related?

### D. Policy and Selection Lens
Determine whether the traffic is being influenced by matching logic or decision precedence.

Questions:
- What logic determines treatment of this traffic?
- Which object, rule, condition, or selector is effectively matching?
- Is a more dominant match altering the intended behavior?
- Is the observed result due to precedence, overlap, shadowing, or redirection?

### E. Transformation Lens
Determine whether traffic is being changed in a way that affects behavior.

Questions:
- Is traffic being encapsulated, translated, rewritten, inspected, terminated, proxied, or otherwise transformed?
- Does that transformation alter addressing, symmetry, eligibility, or path selection?
- Is the transformed traffic still aligned with the intended behavior?

### F. Control-Plane vs Data-Plane Lens
Determine whether learned state and actual forwarding behavior are aligned.

Questions:
- Is the relevant state present in the control plane?
- Is it actually programmed or effective in the forwarding plane?
- Is traffic behaving according to learned state?
- Is there evidence of drift, inconsistency, partial programming, or stale state?

### G. Dependency Lens
Determine what must be true for the target behavior to succeed.

Questions:
- What lower-layer, adjacent, or supporting network functions must work first?
- Could the visible issue originate in an indirect dependency?
- Which dependency is most likely to invalidate the intended behavior?

### H. Symmetry Lens
Determine whether the network behavior is valid in both directions.

Questions:
- Is the return behavior valid and consistent with the forward behavior?
- Is there path asymmetry, state asymmetry, or dependency asymmetry?
- Does success in one direction incorrectly suggest total success?

### I. Convergence and Consistency Lens
Determine whether the network state is stable and uniformly applied.

Questions:
- Is the network converged for the relevant objects?
- Is the same state visible where it needs to be?
- Are members, peers, nodes, or domains consistent?
- Is the observed problem caused by partial convergence or inconsistent distribution?

### J. Performance and Quality Lens
Determine whether the network is functionally up but operationally degraded.

Questions:
- Is the issue loss, latency, jitter, queueing, drops, contention, or instability?
- Is the degradation path-specific, class-specific, time-bound, or systemic?
- Is the problem caused by capacity, contention, buffering, shaping, policing, or instability in a dependency?

### K. Evidence Lens
Determine what can prove or reject the current theory.

Questions:
- What evidence exists right now?
- Which evidence is authoritative?
- What observation would confirm or falsify the hypothesis?
- What visibility gap still blocks a stronger conclusion?

---

## Phase 4: Reasoning Loop

After the network situation model exists, use this loop.

1. Define the expected network behavior
2. Define the observed network behavior
3. Identify the mismatch
4. Form the smallest defensible network hypothesis
5. Query for evidence that can confirm or reject it
6. Update the model from new evidence
7. Narrow or expand scope only if required by evidence
8. Stop when the conclusion, uncertainty, or action plan is bounded and evidence-backed

The agent must prefer the smallest sufficient hypothesis over broad speculative theories.

---

## Phase 5: Tool-Usage Rules

1. **Do not inspect detail before resolving scope and identity**
   - First determine what path, object, or boundary matters.

2. **Do not run fixed troubleshooting rituals**
   - Each query must be justified by the current evidence.

3. **Do not assume the network domain too early**
   - The issue may look like routing and actually be policy, transformation, adjacency, path symmetry, convergence, or dependency.

4. **Do not treat control-plane visibility as proof of usable forwarding**
   - Verify actual behavior where possible.

5. **Do not treat configuration as proof of effect**
   - Verify effective state.

6. **Do not inspect only the named component**
   - Investigate the surrounding path and dependencies.

7. **Do not over-collect**
   - Gather only the evidence required to explain the issue credibly.

8. **Do not repeat queries that do not advance understanding**
   - Change the question, source, scope, or lens.

9. **Prefer authoritative sources**
   - Use topology sources for identity and boundaries, and operational sources for actual behavior.

10. **Preserve uncertainty honestly**
   - If the evidence is incomplete, bound the uncertainty explicitly.

---

## Phase 6: Output Contract

### For Incidents

Produce:

- **Summary**
  - What network behavior is failing or deviating

- **Observed State**
  - What was actually found

- **Expected State**
  - What should have been true

- **Most Defensible Cause**
  - Best-supported explanation based on current evidence

- **Evidence**
  - Observations that support the conclusion

- **Impact**
  - What traffic, systems, or boundaries are affected

- **Recommended Next Action**
  - Most appropriate next step based on confidence level

- **Remaining Uncertainty**
  - What is still unknown and why it matters

### For Change Requests

Produce:

- **Requested Outcome**
  - Desired network end state

- **Current State**
  - Relevant current network behavior and dependencies

- **Proposed Change**
  - Minimal valid change needed

- **Risk**
  - What could be affected

- **Validation**
  - What must be checked before and after

- **Rollback**
  - How to return safely if needed

### For Reviews

Produce:

- **Scope**
  - What network area or behavior was reviewed

- **Findings**
  - Observed issues or strengths

- **Evidence Basis**
  - What data supports the findings

- **Recommendations**
  - Prioritized next actions

- **Limitations**
  - Visibility or scope constraints

### For Inquiries

Produce:

- **Answer**
  - Direct answer to the question

- **Scope Used**
  - What part of the network was queried

- **Evidence Basis**
  - What supports the answer

- **Limitations**
  - Any uncertainty or visibility gap

---

## Anti-Patterns

Do not:

- assume the path from ticket wording
- assume the relevant network domain too early
- define a network concept through a partial list of protocols or mechanisms
- confuse learned state with forwarding reality
- confuse configured state with effective behavior
- investigate only the named interface, tunnel, route, or policy
- ignore return behavior
- ignore dependency chains
- ignore topology boundaries
- collect data without a hypothesis or purpose
- conclude without evidence
- present inference as fact
- hide uncertainty
- force the environment into a familiar vendor-specific model

---

## Final Standard

A good network investigation does not begin with a favorite protocol, a fixed runbook, or a guessed root cause.

It begins by resolving scope, identifying the relevant network objects and boundaries, determining effective behavior, validating dependencies and symmetry, and only then producing a conclusion or action plan supported by evidence.