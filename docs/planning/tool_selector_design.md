# Plan: Refactor MCP Tool Selection — Intent + LLM Evaluation

## Context

The current tool selection system has selection logic duplicated between `evidence_collector.py` and `investigator.py`, with different strategies (multi-tool vs single-tool). Both dump all candidate tools to the LLM in one shot, combining selection + arg binding in a single overwhelmed call. There is no per-tool reasoning about relevance — the LLM just picks from a list.

**Goal**: Centralize tool selection into a two-phase pipeline:
1. **Intent-based retrieval**: Short keyword phrases → semantic search → N candidate tools
2. **LLM per-tool evaluation**: Each candidate tool is individually assessed ("does this tool help me get the info I need?") — making selection intelligent rather than a bulk pick

This replaces the current "dump all tools and let LLM pick" approach with a reasoned, per-tool evaluation.

---

## Architecture

### New module: `src/core/tool_selector.py`

Separate from `CapabilityRegistry` (which is a static catalog). Tool selection is a runtime operation involving LLM calls, tenant context, and state-dependent reasoning.

### Pipeline: 4 phases

```
Phase 1: Intent Generation (LLM)
    "What info do I need?" → ["keyword query 1", "keyword query 2"]
         ↓
Phase 2: Semantic Retrieval (Qdrant)
    Each intent → vector search → merge + deduplicate → N candidates
         ↓
Phase 3: Per-Tool Evaluation (LLM, batched ≤5 per call)
    For EACH candidate: "What am I looking for? Does THIS tool help?" → relevant/not + reasoning
         ↓
Phase 4: Argument Binding (LLM, only for approved tools)
    For each approved tool → configure args with full context
```

---

## Data Models (`src/core/models.py`)

```python
class ToolIntent(BaseModel):
    """Short keyword query for semantic tool search."""
    query: str          # 2-6 word search query
    goal: str = ""      # What info this intent seeks (optional, for traceability)

class ToolCandidate(BaseModel):
    """A tool retrieved by semantic search, awaiting LLM evaluation."""
    tool_name: str
    description: str
    args_schema: Dict[str, Any] = Field(default_factory=dict)
    search_score: float = 0.0
    source_intent: str = ""

class ToolEvaluation(BaseModel):
    """LLM judgment on a single candidate tool."""
    tool_name: str
    relevant: bool          # Does this tool help gather the needed info?
    reasoning: str          # Why or why not (1-2 sentences)
    priority: int = 0       # Relative priority (1=highest) among approved tools

class ToolSelection(BaseModel):
    """Approved tool with bound arguments, ready for execution."""
    name: str
    args: Dict[str, Any]
    evaluation: ToolEvaluation
```

---

## Context Objects

```python
@dataclass
class ToolSelectionContext:
    """All context needed for tool selection decisions."""
    ticket_text: str
    component: Optional[Component] = None
    components: List[Component] = field(default_factory=list)
    hypothesis: Optional[Hypothesis] = None       # For investigator mode
    facts: Dict[str, Any] = field(default_factory=dict)
    path_context: str = ""
    evidence_summaries: str = ""
    mode: str = "evidence"  # "evidence" | "investigation" | "relational"
    # Relational mode fields
    source_component: Optional[Component] = None   # For relational mode
    target_component: Optional[Component] = None   # For relational mode
```

---

## `ToolSelector` Class (`src/core/tool_selector.py`)

```python
class ToolSelector:
    def __init__(self, customer_id: str):
        self.customer_id = customer_id
        self.llm = LLMFactory.get_model_for_agent("evidence_collector")

    async def select_tools(
        self,
        context: ToolSelectionContext,
        max_intents: int = 3,
        max_candidates_per_intent: int = 5,
        max_tools: int = 5,
    ) -> List[ToolSelection]:
        """Full pipeline: intents → retrieval → evaluation → arg binding."""
        # 1. Generate intents
        intents = await self.generate_intents(context, max_intents)
        # 2. Retrieve candidates via semantic search
        candidates = await self.retrieve_candidates(intents, max_candidates_per_intent)
        # 3. Evaluate candidates (batched, ≤5 per LLM call)
        evaluations = await self.evaluate_candidates(candidates, context)
        # 4. Filter approved + bind arguments
        approved = [e for e in evaluations if e.relevant]
        approved.sort(key=lambda e: e.priority)
        approved = approved[:max_tools]
        if not approved:
            return []
        # 5. Bind arguments for approved tools
        selections = await self.bind_arguments(approved, context)
        return selections

    async def generate_intents(self, context: ToolSelectionContext, max_intents: int = 3) -> List[ToolIntent]:
        """Phase 1: LLM generates keyword search queries."""

    async def retrieve_candidates(self, intents: List[ToolIntent], limit_per_intent: int = 5) -> List[ToolCandidate]:
        """Phase 2: Semantic search per intent, merge + deduplicate."""

    async def evaluate_candidates(self, candidates: List[ToolCandidate], context: ToolSelectionContext) -> List[ToolEvaluation]:
        """Phase 3: LLM evaluates candidates in batches of ≤5."""

    async def bind_arguments(self, evaluations: List[ToolEvaluation], context: ToolSelectionContext) -> List[ToolSelection]:
        """Phase 4: LLM constructs args only for approved tools."""

    def _get_brute_force_candidates(self, context: ToolSelectionContext) -> List[ToolCandidate]:
        """Fallback: safe read-only tools filtered by vendor/role."""
```

---

## Prompt Designs

### Phase 1: Intent Generation

Three mode variants, all producing the same output format:

**Evidence mode** (per-component):
```
Ticket: "{ticket_text}"
Component: {component.id} (Role: {component.role}, Vendor: {vendor})
All components: {components_summary}

Generate 1-3 SHORT tool-search queries (2-6 words each).
RULES: keyword-style, include vendor, focus on category, no IPs, CONFIGURATION-FIRST.
{path_context if present}

Return JSON: {"intents": ["query 1", "query 2"]}
```

**Investigation mode** (per-hypothesis):
```
Hypothesis: "{hypothesis.summary}"
Rationale: {hypothesis.rationale}
Components: {component_ids_and_roles}
Facts collected: {facts_keys_summary}
{evidence_summaries if present}

Generate 1-2 SHORT tool-search queries (2-6 words each) to find tools
that verify/disprove this hypothesis.
Same rules: keywords, vendor, category, CONFIGURATION-FIRST.

Return JSON: {"intents": ["query 1", "query 2"]}
```

**Relational mode** (source→target pair):
```
Ticket: "{ticket_text}"
Source: {src.id} (Role: {src.role}, Vendor: {src.vendor})
Destination: {dst.id} (Role: {dst.role}, Vendor: {dst.vendor})

Generate 1-2 SHORT tool-search queries for tools that check the RELATIONSHIP
or REACHABILITY between source and destination.
Focus: route lookup, policy check, NAT mapping, path trace, connectivity.
CONFIGURATION-FIRST.

Return JSON: {"intents": ["query 1", "query 2"]}
```

Key change for investigator: currently generates natural-language sentences ("retrieve current configuration..."). Instead, generate keyword queries — same format as evidence_collector. This unifies the retrieval path.

### Phase 3: Per-Tool Evaluation (the core innovation)

**Batched evaluation — max 5 candidates per LLM call.**

If there are >5 candidates, split into batches: e.g., 11 candidates → 3 calls (5 + 5 + 1).

```
You are evaluating diagnostic tools for an IT support investigation.

INVESTIGATION GOAL:
Ticket: {ticket_text}
{component/hypothesis context depending on mode}
What we need to determine: {derived from intents/goals}

AVAILABLE CONTEXT:
- Components: {component_ids_and_roles}
- Known facts: {facts_keys}
- {evidence_summaries if investigation mode}

CANDIDATE TOOLS TO EVALUATE:
1. {tool_1_name}: {description}
   Required params: {required_params_summary}
   Optional params: {optional_params_summary}

2. {tool_2_name}: {description}
   Required params: {required_params_summary}
   Optional params: {optional_params_summary}
...

For EACH tool, answer:
1. Does the tool's PURPOSE match what we're looking for?
2. Can we provide the REQUIRED parameters from available context (components, facts)?
3. Will the tool's OUTPUT contribute useful diagnostic data?
4. CONFIGURATION-FIRST: Prefer config-reading tools over live traffic.
5. If a tool was already executed (check evidence summaries), mark as not relevant.

Return JSON list (one entry per tool, same order):
[
    {"tool_name": "...", "relevant": true/false, "reasoning": "1-2 sentences", "priority": 1-5},
    ...
]

Priority: 1=most critical, 5=nice-to-have. Only assign priority if relevant=true.
```

### Phase 4: Argument Binding

Only for tools where `relevant=true`. Single LLM call for all approved tools:

```
Component: {component.id} (Role: {role}, Vendor: {vendor})
{For relational: Source: {src.id}, Destination: {dst.id}}

APPROVED TOOLS (configure arguments for each):
1. {tool_name}: {description}
   Schema: {full_args_schema}
   {insight_text if available}

2. ...

GUIDELINES:
1. For 'device', 'host', 'hostname' args: use the executor component ID ({component.id or src.id}).
2. For 'target', 'ip', 'address', 'destination' args: use the target component ID ({target or dst.id}).
3. Analyze Schema: distinguish mandatory vs optional.
4. ANTI-HALLUCINATION: Do NOT invent parameters. If mandatory param is missing, SKIP that tool.
5. READ-ONLY only. No modify/delete/configure.

Return JSON list:
[
    {"name": "tool_name_1", "args": {...}},
    {"name": "tool_name_2", "args": {...}}
]
```

---

## Integration with Agents

### Evidence Collector (`src/agents/evidence_collector.py`)

**Per-component selection** — replace `_select_tools_for_component()` (lines 424-580):

```python
selector = ToolSelector(customer_id=customer_id)
context = ToolSelectionContext(
    ticket_text=ticket_text,
    component=component,
    components=all_components,
    facts=state.get("facts", {}),
    path_context=path_context,
    mode="evidence",
)
selections = await selector.select_tools(context, max_tools=5)
# selections is List[ToolSelection] — name + args ready for execution
```

**Relational evidence** — replace `_collect_relational_evidence()` (lines 246-397):

The pair-building logic (executor/target split, adjacent fallback, cap at 5 pairs) stays in evidence_collector. But per-pair tool selection now uses ToolSelector:

```python
for src_comp, dst_comp in pairs:
    selector = ToolSelector(customer_id=customer_id)
    context = ToolSelectionContext(
        ticket_text=ticket_text,
        source_component=src_comp,
        target_component=dst_comp,
        components=components,
        mode="relational",
    )
    selections = await selector.select_tools(context, max_intents=2, max_tools=3)
    # Execute each selection with AdaptiveExecutor...
```

### Investigator (`src/agents/investigator.py`)

Replace lines 61-195 (intent generation + semantic search + tool selection):

```python
selector = ToolSelector(customer_id=customer_id)
context = ToolSelectionContext(
    ticket_text=state["ticket"].text,
    component=target_component,  # derived from hypothesis
    components=state.get("components", []),
    hypothesis=target_hypothesis,
    facts=state.get("facts", {}),
    path_context=path_str,
    evidence_summaries=evidence_context,
    mode="investigation",
)
selections = await selector.select_tools(context, max_tools=3)
# Execute first (highest priority) selection, then next if needed
```

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `src/core/tool_selector.py` | **CREATE** | New centralized ToolSelector class |
| `src/core/models.py` | **EDIT** | Add ToolIntent, ToolCandidate, ToolEvaluation, ToolSelection, ToolSelectionContext |
| `src/agents/evidence_collector.py` | **EDIT** | Replace `_select_tools_for_component()` and `_collect_relational_evidence()` internals with ToolSelector |
| `src/agents/investigator.py` | **EDIT** | Replace intent+search+selection block (lines 61-195) with ToolSelector |

Files NOT modified (remain as-is):
- `src/core/registry.py` — static catalog, unchanged (ToolSelector uses it internally)
- `src/core/qdrant.py` — vector store, unchanged (ToolSelector uses it internally)
- `src/core/adaptive_executor.py` — execution layer, unchanged (agents still call it after selection)
- `src/core/safety.py` — safety checks still applied in agents before execution
- `src/utils/arg_sanitizer.py` — sanitization still applied post-selection in agents

---

## Execution Order

1. Add data models to `src/core/models.py` (ToolIntent, ToolCandidate, ToolEvaluation, ToolSelection, ToolSelectionContext)
2. Create `src/core/tool_selector.py` with full `ToolSelector` class (all 4 phases + brute-force fallback)
3. Refactor `evidence_collector.py`:
   - Replace `_select_tools_for_component()` with ToolSelector calls
   - Refactor `_collect_relational_evidence()` to use ToolSelector in relational mode
   - Keep execution loop, safety checks, arg sanitization, adaptive executor usage
4. Refactor `investigator.py`:
   - Replace intent+search+selection block with ToolSelector calls
   - Keep execution, arg auto-correction, safety checks, recovery loop
5. Remove dead code: `_get_brute_force_tools()` moves into ToolSelector

---

## Key Design Decisions

1. **Batch evaluation, 5 candidates per call**: Split candidates into batches of ≤5 per LLM call. If 11 candidates → 3 calls (5+5+1). Balances quality per-tool reasoning with API efficiency.
2. **Full pipeline**: ToolSelector returns ready-to-execute `ToolSelection` objects with bound args. Agents just execute.
3. **Evaluation separate from arg binding**: LLM evaluates relevance FIRST (lightweight — name+description+schema summary). Arg binding only for approved tools (heavier — full schema + context). Two distinct cognitive tasks, two distinct LLM calls.
4. **Three modes**: `evidence` (per-component), `investigation` (per-hypothesis), `relational` (source→target pair). Same pipeline, different intent generation prompts.
5. **Insights injection**: Tool insights from Qdrant (`get_tool_insights`) fetched and injected into arg binding prompt.
6. **Brute-force fallback preserved**: If semantic search yields zero candidates, fall back to safe read-only tools filtered by vendor/role (current `_get_brute_force_tools()` logic).
7. **Safety/governance checks remain in agents**: `is_safe_tool()` and `is_tool_allowed_for_tenant()` still called by agents before execution, not inside ToolSelector.

---

## Verification

1. Run the full pipeline with a test ticket to verify tool selection produces sensible results
2. Check logs for: intent generation, semantic search results, per-tool evaluation reasoning (relevant/not + why), approved tools, bound arguments
3. Compare output quality vs current approach — evaluation reasoning should explain WHY each tool was selected/rejected
4. Verify batch splitting works correctly (e.g., 11 candidates → 3 batches of 5+5+1)
5. Verify tenant isolation: `customer_id` flows through all ToolSelector calls
6. Verify safety: blocked tools never appear in final selections
7. Verify relational mode: source/target args correctly bound for cross-component tools
8. Verify investigator now produces keyword intents (not sentences) for consistent retrieval
