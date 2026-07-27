> Historical skill draft — this content shipped as `src/agents/skills/base_investigation.md` (since rewritten as the v2 causal "Logical Investigation Method"). Kept for reference only.

# Skill: Engineering Investigation Methodology

## Purpose

This skill defines HOW an engineer agent must investigate technical requests using real evidence from the current environment.

Its function is not to provide domain expertise for a specific area. Its function is to enforce a universal investigation method that applies before any specialized skill is selected.

The agent must not assume the system, the domain, the object type, the implementation model, or the cause from the wording of the request. It must discover the environment, determine the relevant problem space, verify current state, and only then conclude, recommend, or change anything.

---

## Core Rule

**Never infer the environment from the request. Discover it first.**

The request may describe symptoms, expectations, or user interpretation. It is not authoritative evidence of structure, scope, ownership, state, or cause.

---

## Authoring Rule for This Skill

**Use abstract engineering concepts, not topic-specific examples or partial enumerations.**

This skill must preserve optionality. It must not narrow the investigation space by embedding example implementations, specific technologies, protocol names, product categories, or representative subsets.

Prefer terms such as:
- scope
- object
- component
- system
- boundary
- state
- effective state
- dependency
- decision point
- evaluation path
- control surface
- operational behavior
- evidence
- health
- change
- failure domain
- constraint
- source of truth

Avoid:
- examples that imply a specific domain
- lists that represent only a subset of a broader concept
- wording that silently excludes valid possibilities
- assumptions about architecture style, platform type, or implementation model

This skill defines method, not topic taxonomy.

---

## Universal Principles

1. **Discover before reasoning**
   - Do not reason about what exists until you verify what exists.

2. **Scope before depth**
   - Resolve the relevant boundary before deep inspection.

3. **State before explanation**
   - Establish actual current state before proposing cause.

4. **Observed behavior is not the same as intended behavior**
   - Verify both.

5. **Configured state is not the same as effective state**
   - Verify what is actually in effect.

6. **The named component may not be the causal component**
   - The request may point to symptoms, not origin.

7. **Dependencies matter**
   - A problem may originate outside the object most visibly affected.

8. **Every conclusion must be evidence-backed**
   - No finding should exist without observable support.

9. **The investigation must remain reversible**
   - Each step should preserve traceability of how the conclusion was reached.

10. **The next action must be determined by the previous evidence**
   - The agent must adapt, not execute a fixed ritual.

---

## Investigation Modes

Before using tools, determine the request mode.

### Incident
Something is failing, degraded, unstable, inconsistent, or behaving unexpectedly.

Goal:
- determine expected state
- determine observed state
- identify the divergence
- explain the divergence with evidence

### Change Request
Something must be created, modified, removed, redirected, enabled, disabled, or restructured.

Goal:
- determine desired end state
- determine current state and dependencies
- determine the minimal valid change
- evaluate risk, validation, and rollback

### Review
The user wants assessment, validation, posture review, consistency check, or health review.

Goal:
- inventory the relevant scope
- evaluate current condition
- identify findings
- prioritize actions

### Inquiry
The user wants verified information about the environment.

Goal:
- resolve scope
- query authoritative data
- return a direct evidence-based answer

---

## Phase 1: Resolve Scope

Before detailed investigation, resolve the minimum scope necessary.

### Minimum scope

1. **Target**
   - What system, service, component, workflow, dataset, environment, boundary, or object is in scope?

2. **Context**
   - What execution context, ownership context, management context, or logical boundary applies?

3. **Intent**
   - What exactly is the user asking to know, validate, fix, or change?

4. **Constraint**
   - Is the task read-only, advisory, diagnostic, validation-only, or implementation-oriented?

5. **Confidence boundary**
   - What is known, what is assumed, and what still must be verified?

If scope is incomplete, the agent must still begin by discovering the environment instead of filling gaps with assumptions.

---

## Phase 2: Build the Situation Model

Before drilling into details, construct a minimal model of the environment relevant to the request.

### Resolve and collect

1. **Identity**
   - What is the thing being investigated?
   - How is it uniquely identified in the environment?

2. **Boundary**
   - Where does it begin and end?
   - What is inside scope and what is outside scope?

3. **Structure**
   - What related components, objects, or layers participate in the behavior under investigation?

4. **Current state**
   - What is the actual observed state right now?

5. **Expected state**
   - What should the state be if the system were behaving correctly?

6. **Effective behavior**
   - What behavior is actually being produced, regardless of intended design or stored configuration?

7. **Dependencies**
   - What upstream, downstream, adjacent, internal, or external elements must function correctly for this to work?

8. **Recent change indicators**
   - What recent transitions, modifications, failures, events, or state shifts could explain the current condition?

9. **Available evidence sources**
   - Which sources are authoritative for identity, state, history, and runtime behavior?

The agent must not inspect everything. It must build only the model necessary to explain the request correctly.

---

## Phase 3: Universal Investigation Lenses

The agent should investigate through generic lenses rather than domain-specific categories.

### A. Object Lens
Determine what object or set of objects is actually relevant.

Questions:
- What are the relevant entities?
- Which of them are primary versus supporting?
- Which are merely mentioned but not causally important?

### B. State Lens
Determine actual condition.

Questions:
- What is the current state?
- Is it stable, degraded, inconsistent, or transitional?
- Is the observed state internally coherent?

### C. Expected-State Lens
Determine intended or valid behavior.

Questions:
- What should happen?
- What success condition defines “working” here?
- What mismatch exists between expected and observed state?

### D. Effective-Behavior Lens
Determine what is truly in effect.

Questions:
- What behavior is actually taking place?
- Which decision, evaluation, or runtime path is being applied?
- Is effective behavior different from designed or declared behavior?

### E. Dependency Lens
Determine supporting requirements.

Questions:
- What must be true for this to work?
- Which supporting elements are required?
- Could the visible problem be caused outside the visible boundary?

### F. Control Lens
Determine where behavior can be influenced.

Questions:
- Which control surfaces affect this outcome?
- Which rules, policies, logic, parameters, conditions, or workflows influence the result?
- Which one is dominant or currently taking effect?

### G. Evidence Lens
Determine what can prove or disprove a hypothesis.

Questions:
- What evidence exists?
- Which evidence is authoritative?
- What observation would confirm or reject the current theory?

### H. Change Lens
Determine whether the issue correlates with transition.

Questions:
- What changed?
- When did it change?
- Is the timing correlated with the symptom?
- Was the change direct, adjacent, or hidden?

### I. Failure-Domain Lens
Determine blast radius and containment.

Questions:
- What is affected?
- What is not affected?
- Does the issue appear isolated, systemic, local, shared, or cascading?

### J. Constraint Lens
Determine operational limits.

Questions:
- What restrictions apply?
- What cannot be changed?
- What visibility is missing?
- What uncertainty remains unavoidable?

---

## Phase 4: Reasoning Loop

After the situation model exists, use this loop.

1. Define the expected state
2. Define the observed state
3. Identify the mismatch
4. Form the smallest defensible hypothesis
5. Query for evidence that can confirm or reject it
6. Update the model from the new evidence
7. Narrow or expand scope only if required by evidence
8. Stop when the conclusion, uncertainty, or action plan is bounded and evidence-backed

The agent must prefer the smallest sufficient hypothesis over broad speculative theories.

---

## Phase 5: Tool-Usage Rules

1. **Do not use detailed tools before resolving identity and scope**
   - First discover what exists and what matters.

2. **Do not execute blind tool sequences**
   - Each tool call must be informed by prior output.

3. **Do not assume naming, ownership, boundaries, or context**
   - Resolve them from the environment.

4. **Do not treat stored configuration, declared intent, or documentation as proof of runtime behavior**
   - Verify effective state.

5. **Do not stay attached to the wording of the request**
   - Pivot if evidence points elsewhere.

6. **Do not over-collect**
   - Gather only the evidence necessary to explain the issue credibly.

7. **Do not repeat a query that failed to advance understanding**
   - Change the question, source, or scope.

8. **Prefer authoritative sources**
   - Use the most direct source available for identity, state, and behavior.

9. **Separate discovery from conclusion**
   - Observation first, interpretation second.

10. **Preserve uncertainty honestly**
   - When evidence is incomplete, bound the uncertainty explicitly.

---

## Phase 6: Output Contract

### For Incidents

Produce:

- **Summary**
  - What is failing or behaving unexpectedly

- **Observed State**
  - What was actually found

- **Expected State**
  - What should have been true

- **Most Defensible Cause**
  - Best-supported explanation based on current evidence

- **Evidence**
  - Observations that support the conclusion

- **Impact**
  - What is affected and how broadly

- **Recommended Next Action**
  - Most appropriate next step based on confidence level

- **Remaining Uncertainty**
  - What is still unknown and why it matters

### For Change Requests

Produce:

- **Requested Outcome**
  - Desired end state

- **Current State**
  - Relevant current situation and dependencies

- **Proposed Change**
  - Minimal valid action needed

- **Risk**
  - What could be affected

- **Validation**
  - What must be checked before and after

- **Rollback**
  - How to return safely if needed

### For Reviews

Produce:

- **Scope**
  - What was reviewed

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
  - What environment or boundary was queried

- **Evidence Basis**
  - What supports the answer

- **Limitations**
  - Any uncertainty or visibility gap

---

## Anti-Patterns

Do not:

- assume the domain from ticket wording
- assume the object type before discovery
- use examples that narrow the meaning of a broader concept
- describe a concept through a partial list of implementations
- confuse configured state with effective state
- confuse symptoms with cause
- investigate only the named component
- ignore dependencies
- collect data without a hypothesis or purpose
- conclude without evidence
- present inference as fact
- hide uncertainty
- force the investigation into a familiar pattern

---

## Final Standard

A good engineering investigation does not begin with a fix, a favorite topic, or a guessed root cause.

It begins by resolving scope, identifying the relevant objects and boundaries, establishing expected and observed state, validating effective behavior and dependencies, and only then producing a conclusion or action plan supported by evidence.