# Hypothesis Agent

## Description
The Hypothesis Agent is the reasoning engine of the system. It consumes the ticket, collected facts, topology graph, baselines, and known changes to generate a ranked list of potential explanations (hypotheses). It also performs **path analysis** when topology data exists, identifying candidate flow paths, breakpoints, and evidence gaps.

## Role in Graph
- **Node Name:** `hypothesis_agent`
- **Upstream:** `enricher_agent`
- **Downstream:** `scoring_agent` → `supervisor`

## Inputs
- `state["ticket"]`: Ticket text.
- `state["facts"]`: Structured facts extracted by the Enricher.
- `state["hypotheses"]`: Existing hypotheses (if any).
- `state["topology_nodes"]`, `state["topology_edges"]`: Entity relationship graph.
- `state["client_context"]`: For baselines and known changes.

## Outputs
- `state["hypotheses"]`: A list of `Hypothesis` objects, ranked by probability.
- `state["path_analysis"]`: (when topology exists) `PathAnalysis` with candidate paths, breakpoints, and suggested probes.

## Prompts

### Hypothesis Generation & Ranking
**Context injected into prompt:**
- Ticket text
- Collected facts
- Topology graph (formatted as `src ──[relation]──> tgt (confidence)`)
- Baselines (normal values per component)
- Known changes (recent modifications)
- Existing hypotheses

**Dual-Role Adaptation:**
1. **VALIDATION/INQUIRY** tickets → Act as investigator/analyst, formulate neutral verification hypotheses.
2. **INCIDENT/PROBLEM** tickets → Act as troubleshooter, focus on root cause.

**Advanced Troubleshooting Mindset:**
- Analyze systems layer by layer (physical → logical → application).
- Consider configuration drift, resource constraints, access control policies, service dependencies.
- Ground reasoning in vendor-specific architecture when identifiable.

### Path Analysis (when topology exists)
After hypothesis generation, a second LLM call performs:
1. **Path Synthesis**: Identify candidate paths between source and destination implied by the ticket.
2. **Constraint Evaluation**: For each hop, evaluate constraints (route exists? policy allows? NAT correct?).
3. **Breakpoint Detection**: Identify edges where constraints failed or are unknown.
4. **Verification Suggestions**: Propose read-only diagnostic probes to fill evidence gaps.

**Output Contract:**
- `CandidatePath[]` with hops, constraints (passed/failed/unknown), confidence, status (viable/blocked/incomplete).
- `MostLikelyBreakpoints[]` with edge, constraint type, and reasoning.
- `MissingEvidence[]` + `SuggestedProbes[]`.

## Key Logic & Interactions
- **LLM Model:** Uses `LLM_MODEL_HYPOTHESIS` (e.g., `gpt-5.2`) — requires strong reasoning capabilities.
- **Iterative**: Runs in a loop. First pass guesses from ticket context. Subsequent passes refine based on new evidence.
- **Status Management**: Hypotheses start as `proposed`, move to `verifying` (investigator), then `verified` or `rejected`.
- **Fast Mode**: When `TEST_MODE_FAST` is enabled, returns exactly 1 hypothesis.
