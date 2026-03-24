# Tool Selection Pipeline — Full Technical Reference

> **Purpose**: This document describes the complete tool selection procedure as currently implemented.
> Every step from agent invocation through tool execution is traced with file paths, line numbers,
> data models, and a worked example.

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [Full Pipeline Flow Diagram](#2-full-pipeline-flow-diagram)
3. [Phase 1 — Intent Generation](#3-phase-1--intent-generation)
4. [Phase 2 — Semantic Retrieval](#4-phase-2--semantic-retrieval)
5. [Phase 3 — Per-Tool Evaluation](#5-phase-3--per-tool-evaluation)
6. [Phase 4 — Argument Binding](#6-phase-4--argument-binding)
7. [Phase 5 — Prerequisite Resolution](#7-phase-5--prerequisite-resolution)
8. [Phase 5b — Runtime Dependency Resolution](#8-phase-5b--runtime-dependency-resolution)
9. [Tool Indexing Pipeline](#9-tool-indexing-pipeline)
10. [Qdrant Tool Catalog Schema](#10-qdrant-tool-catalog-schema)
11. [Execution & Adaptive Healing](#11-execution--adaptive-healing)
12. [Safety & Governance](#12-safety--governance)
13. [Worked Example](#13-worked-example)
14. [Configuration Parameters](#14-configuration-parameters)
15. [File Reference](#15-file-reference)

---

## 1. High-Level Overview

The tool selection pipeline is a **4-phase LLM-powered system** that discovers, evaluates, and
configures diagnostic tools for execution. Two agents invoke it:

| Agent | Mode | Purpose |
|---|---|---|
| `evidence_collector` | `"evidence"` / `"relational"` | Gather diagnostic data per component |
| `investigator` | `"investigation"` | Verify/disprove top hypothesis via open questions |

The pipeline lives in `ToolSelector` (`src/core/tool_selector.py`). Each invocation runs:

```
Phase 1: Intent Generation      — LLM produces 1-3 keyword search queries
Phase 2: Semantic Retrieval      — Qdrant vector search per intent (+ vendor filter)
Phase 3: Per-Tool Evaluation     — LLM assesses each candidate (batched ≤5)
Phase 4: Argument Binding        — LLM configures args for approved tools
Phase 5: Prerequisite Resolution — (optional) resolve missing params via prereq tools
```

Entry point: `ToolSelector.select_tools(context, max_intents=3)` → returns `List[ToolSelection]`

---

## 2. Full Pipeline Flow Diagram

```
 AGENT (evidence_collector / investigator)
 Creates ToolSelectionContext with:
   ticket_text, component, components, facts,
   hypothesis (investigation only), path_context,
   evidence_summaries, mode
           │
           ▼
┌─────────────────────────────────────────┐
│  PHASE 1: INTENT GENERATION (LLM)      │
│                                         │
│  Input:  ToolSelectionContext            │
│  Prompt: mode-specific builder          │
│    ├─ "evidence"      → _build_evidence_intent_prompt()
│    ├─ "investigation" → _build_investigation_intent_prompt()
│    └─ "relational"    → _build_relational_intent_prompt()
│                                         │
│  Output: List[ToolIntent]               │
│    e.g. ["firewall routing table",      │
│          "firewall policy rules"]       │
│                                         │
│  Fallback: _fallback_intents() if       │
│            LLM fails                    │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  PHASE 2: SEMANTIC RETRIEVAL (Qdrant)   │
│                                         │
│  For each intent:                       │
│    vector_store.search_tool_catalog(    │
│      intent=query,                      │
│      vendor=component.vendor,  ◄── auto │
│      read_only=True,                    │
│      limit=10,                          │
│      score_threshold=0.15               │
│    )                                    │
│                                         │
│  Dedup across intents (by tool_name)    │
│  Safety filter (_is_safe)              │
│  Registry lookup (get_tool)             │
│                                         │
│  ┌─ IF 0 results + vendor filter ──┐   │
│  │  Retry ALL intents WITHOUT       │   │
│  │  vendor filter (fallback)        │   │
│  └──────────────────────────────────┘   │
│                                         │
│  ┌─ IF still 0 results ────────────┐   │
│  │  _get_brute_force_candidates()   │   │
│  │  Scans ALL tools in registry     │   │
│  │  Filters: read_only + vendor +   │   │
│  │  name contains health/status/    │   │
│  │  info/system/summary/overview    │   │
│  └──────────────────────────────────┘   │
│                                         │
│  Output: List[ToolCandidate]            │
│    (10-30 tools typically)              │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  PHASE 3: PER-TOOL EVALUATION (LLM)    │
│                                         │
│  Batched: ≤5 candidates per LLM call   │
│                                         │
│  For EACH tool, LLM answers:           │
│    1. Does PURPOSE match investigation? │
│    2. Is SCOPE appropriate?             │
│       (vendor, device type, domain)     │
│    3. Will OUTPUT contribute useful     │
│       diagnostic data?                  │
│    4. CONFIGURATION-FIRST preference?   │
│                                         │
│  Returns per tool:                      │
│    relevant: bool                       │
│    reasoning: "1-2 sentences"           │
│    priority: 1(critical)..5(nice)       │
│                                         │
│  Fallback: if LLM fails → approve ALL  │
│  Sort approved by priority (ascending)  │
│                                         │
│  Output: List[ToolEvaluation]           │
│    (only relevant=true pass through)    │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  PHASE 4: ARGUMENT BINDING (LLM)       │
│                                         │
│  Prompt includes:                       │
│    - Component metadata (full)          │
│    - Ticket text                        │
│    - Prior evidence (max 2000 chars)    │
│    - Known facts (up to 30, with vals)  │
│    - Tool schemas (full JSON)           │
│    - Learned best practices (from       │
│      adaptive_fixes KB)                 │
│                                         │
│  OPERATIONAL vs CONTEXTUAL params:      │
│    OPERATIONAL: limits, pagination,     │
│      timeouts → sensible defaults OK    │
│    CONTEXTUAL: IPs, hostnames, policy   │
│      names → ONLY from ticket/facts/    │
│      evidence. Never hallucinate.       │
│                                         │
│  3-TIER RECOVERY for LLM-omitted tools: │
│    T1: No required params → {}          │
│    T2: All-operational → auto defaults  │
│    T3: Mixed/contextual → trust omit    │
│                                         │
│  Output: List[ToolSelection]            │
│    .name, .args, .evaluation,           │
│    .missing_params (if any)             │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  PHASE 5: PREREQUISITE RESOLUTION      │
│  (Optional — single depth only)        │
│                                         │
│  For tools with exactly 1 missing param:│
│    1. Group by (missing_key, component) │
│    2. Run nested select_tools() to find │
│       a prereq tool for the missing data│
│    3. Execute prereq tool               │
│    4. LLM extracts missing value from   │
│       prereq output                     │
│    5. Rebind original tool with value   │
│                                         │
│  Prereq tools MUST be fully bindable    │
│  (no further missing params — no        │
│   recursion beyond depth 1)             │
│                                         │
│  Drop tools still missing params        │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  EXECUTION LOOP (in agent)             │
│                                         │
│  For each ToolSelection:               │
│    1. Dedup: tool_name::args_sha256     │
│    2. Safety: is_safe_tool()            │
│    3. Governance: is_tool_allowed_for_  │
│       tenant()                          │
│    4. AdaptiveExecutor.execute()        │
│       ├─ Try up to 2 times             │
│       ├─ Inject KB knowledge on retry   │
│       └─ Langfuse tracing              │
│    5. Save evidence → EvidenceStore     │
│                                         │
│  On MissingDependencyError:            │
│    → Phase 5b: Runtime Resolution      │
│    → Retry with resolved args (once)    │
└─────────────────────────────────────────┘
```

---

## 3. Phase 1 — Intent Generation

**File**: `src/core/tool_selector.py`
**Method**: `generate_intents()` (line 86)
**LLM**: `LLMFactory.get_model_for_agent("evidence_collector")`

The LLM generates 1–3 short keyword queries (2–6 words each) based on the selection mode.
The prompt is built by `_build_intent_prompt()` (line 1058) which dispatches to one of three builders:

### 3.1 Evidence Mode (`_build_evidence_intent_prompt`, line 1067)

Used for per-component evidence gathering in `evidence_collector`.

**Inputs provided to LLM**:
- Ticket text
- Component ID, role, vendor
- All components list
- Path context (evidence gaps from path_analysis, if any)

**Rules enforced in prompt**:
1. 2–6 words per query — search-engine style, NOT sentences
2. NO vendor/product names (vendor filtering applied separately in Phase 2)
3. Focus on CATEGORY: routing, policy, interface, performance, logs, database, deployment, container, etc.
4. NO IPs, subnets, or ticket-specific details (those are for arg binding)
5. CONFIGURATION-FIRST: prefer config-reading tools over live traffic tools

**Example output**: `{"intents": ["firewall routing table", "firewall policy rules"]}`

### 3.2 Investigation Mode (`_build_investigation_intent_prompt`, line 1101)

Used by `investigator` to verify/disprove hypotheses.

**Additional inputs**:
- Hypothesis summary + rationale
- Facts collected so far (first 15 keys)
- Evidence collected so far

**Key difference**: Queries target tools that verify the specific hypothesis, not general evidence.

### 3.3 Relational Mode (`_build_relational_intent_prompt`, line 1131)

Used for cross-component connectivity checks (source → destination).

**Additional inputs**:
- Source component (ID, role, vendor)
- Destination component (ID, role, vendor)

**Focus**: route lookup, policy check, NAT mapping, path trace, connectivity.

### 3.4 Fallback Intents (`_fallback_intents`, line 1159)

If the LLM fails to produce parseable JSON:

| Mode | Fallback Intents |
|---|---|
| `relational` | `["route lookup", "policy check"]` |
| `investigation` (with hypothesis) | `["system status health", "configuration check"]` |
| `evidence` (default) | `["{role} status", "{role} configuration"]` |

---

## 4. Phase 2 — Semantic Retrieval

**File**: `src/core/tool_selector.py`
**Method**: `retrieve_candidates()` (line 115)
**Vector Store**: `src/core/qdrant.py` → `search_tool_catalog()` (line 618)

### 4.1 Search Flow

For each intent query:

```
intent.query ("firewall routing table")
     │
     ▼
vector_store.search_tool_catalog(
    intent = "firewall routing table",
    customer_id = <ignored, overridden to "__global__">,
    limit = 10,
    vendor = component.vendor.lower() or None,
    read_only = True,
    score_threshold = 0.15   (QDRANT_SCORE_TOOL_CATALOG)
)
     │
     ▼
1. Embed intent text → 1536-dim vector (OpenAI text-embedding-3-small)
2. Build Qdrant filter:
   - customer_id == "__global__"  (always)
   - vendor == "fortinet"         (if component has vendor)
   - read_only == "true"          (if requested)
3. HNSW vector search (ef=128)
4. Return top-10 scored payloads above threshold
```

### 4.2 Vendor Filter + Fallback

```
                  ┌── vendor from component.vendor ──┐
                  │                                   │
                  ▼                                   │
    Search WITH vendor filter ──── results? ──YES──► Deduplicate + return
                  │                                   │
                  NO                                  │
                  ▼                                   │
    Search WITHOUT vendor filter ── results? ──YES──► Deduplicate + return
                  │                                   │
                  NO                                  │
                  ▼                                   │
    _get_brute_force_candidates() ─────────────────► Return
      Scans ALL registry tools:
        - read_only == True
        - vendor matches (if known)
        - name contains: health, status,
          info, system, summary, overview
```

### 4.3 Deduplication & Filtering

Results from all intents are merged into a single dict keyed by `tool_name` (first-seen wins).
Each candidate is validated:
- `CapabilityRegistry.get_tool(t_name)` — must exist in registry
- `CapabilityRegistry._is_safe(t_name)` — must pass safety check

### 4.4 ToolCandidate Model

```python
@dataclass
class ToolCandidate:
    tool_name: str          # "fortinet_rtm_routes_get"
    description: str        # From tool's MCP description
    args_schema: dict       # Full JSON schema (from tool.args_schema)
    search_score: float     # Qdrant cosine similarity score
    source_intent: str      # Which intent found this tool
    catalog_context: str    # page_content (description + param summary)
    vendor: str             # "fortinet"
    method: str             # "get"
    read_only: bool         # True
    category: str           # "routing"
    param_count: int        # Number of required params
```

---

## 5. Phase 3 — Per-Tool Evaluation

**File**: `src/core/tool_selector.py`
**Method**: `evaluate_candidates()` (line 215) → `_evaluate_batch()` (line 231)

### 5.1 Batch Processing

Candidates are split into batches of ≤5 tools per LLM call.

### 5.2 Context Provided to LLM

The evaluation prompt includes:

| Section | Content |
|---|---|
| Investigation Goal | Ticket text + mode-specific goal (hypothesis / component / relational pair) |
| Components | Comma-separated `"comp_id (role)"` list |
| Known Facts | First 20 fact keys |
| Previous Evidence | Summaries of evidence collected so far |
| Candidate Tools | Per tool: name, search_score, vendor, method, category, description, catalog_context, full JSON schema |

### 5.3 Four-Question Assessment

For each tool, the LLM answers:

1. **PURPOSE** — Does the tool's purpose match what we're investigating?
2. **SCOPE** — Is it appropriate for the correct vendor, device type, domain?
3. **OUTPUT** — Will it contribute useful diagnostic data?
4. **CONFIG-FIRST** — Does it prefer reading config over live traffic?

### 5.4 Output

```python
@dataclass
class ToolEvaluation:
    tool_name: str       # "fortinet_rtm_routes_get"
    relevant: bool       # True/False
    reasoning: str       # "Routing table shows path to destination subnet"
    priority: int        # 1=most critical, 5=nice-to-have, 0=irrelevant
```

Only `relevant=True` tools proceed. Sorted by `priority` ascending.

### 5.5 Fallback

If the LLM call fails entirely, ALL candidates in the batch are approved with
`reasoning="Evaluation failed — approved by fallback"` and `priority=idx+1`.

---

## 6. Phase 4 — Argument Binding

**File**: `src/core/tool_selector.py`
**Method**: `bind_arguments()` (line 341)

### 6.1 Pre-Binding Context

Before calling the LLM, the system gathers:

| Source | Content |
|---|---|
| `vector_store.get_tool_insights()` | Prior successful arg patterns per tool (from adaptive_fixes KB) |
| `_format_component_for_binding()` | Full component metadata (ID, role, vendor, metadata dict) |
| `context.ticket_text` | Full ticket text |
| `context.evidence_summaries` | Prior evidence (max 2000 chars) |
| `context.facts` | Real facts with values (up to 30, excluding `_` prefixed) |

### 6.2 Binding Prompt Guidelines

The LLM is instructed to:

1. **device/host/hostname** args → use component ID
2. **target/address/destination** → extract from TICKET, metadata, facts
3. Use ALL metadata fields to fill matching parameters
4. **Classify each required parameter**:
   - **OPERATIONAL** (limits, pagination, timeouts, sort) → assign sensible defaults
   - **CONTEXTUAL** (IPs, hostnames, policies, interfaces) → ONLY from ticket/facts/evidence
5. **ANTI-HALLUCINATION**: never invent contextual values
6. **READ-ONLY** only — no modify/delete/configure actions
7. Use **KNOWN FACTS** values to bind parameters when key/value matches

### 6.3 Missing Params Detection

After LLM returns bound args, a deterministic check compares bound args against the tool's
JSON schema `required` fields. Any unbound required field is recorded in `missing_params`.

### 6.4 Three-Tier Recovery for LLM-Omitted Tools

If the LLM omitted an approved tool from the binding response entirely:

```
Tier 1: No required params?
  └─ YES → Recover with empty args {}
  └─ NO  ▼

Tier 2: All required params are OPERATIONAL?
  └─ YES → Recover with auto-assigned defaults
           (uses _classify_params_as_operational)
  └─ NO  ▼

Tier 3: Mixed/contextual required params
  └─ Trust the LLM's decision to omit. Don't recover.
```

### 6.5 Output

```python
@dataclass
class ToolSelection:
    name: str                         # "fortinet_rtm_routes_get"
    args: Dict[str, Any]              # {"device": "FW-01", "limit": 100}
    evaluation: ToolEvaluation        # From Phase 3
    missing_params: Dict[str, str]    # {"vdom": "required parameter 'vdom'"}
```

---

## 7. Phase 5 — Prerequisite Resolution

**File**: `src/core/tool_selector.py`
**Method**: `resolve_prerequisites()` (line 538)

Called after Phase 4 for tools that have `missing_params`.

### 7.1 Eligibility Gate

Only tools with **exactly 1 missing param** are eligible. Tools with 2+ missing params are skipped.

### 7.2 Resolution Flow

```
Tool with missing_params = {"vdom": "required VDOM name"}
          │
          ▼
Group by (missing_key, component_id)
          │
          ▼
Nested select_tools() call:
  mode="evidence"
  ticket_text="Need to discover: VDOM name"
  component=same component
          │
          ▼
Filter: only prereq tools with NO missing params (fully bindable)
          │
          ▼
Execute prereq tool → output
          │
          ▼
LLM extracts missing value from prereq output
  (ANTI-HALLUCINATION: only values EXPLICITLY present)
          │
          ▼
Rebind original tool with discovered value
```

### 7.3 Constraints

- **Single-depth only**: prereq tools cannot trigger further prerequisite resolution
- **Max 2 prereqs** per invocation (`max_prereqs=2`)
- **Shared resolution**: tools grouped by same missing param + component share a single prereq execution

After resolution, tools **still** missing params are dropped by the agent (evidence_collector line 107).

---

## 8. Phase 5b — Runtime Dependency Resolution

**File**: `src/core/tool_selector.py`
**Method**: `resolve_runtime_dependency()` (line 699)

Triggered **after execution** when `AdaptiveExecutor` raises `MissingDependencyError`.

### 8.1 MissingDependencyError

```python
class MissingDependencyError(Exception):
    dependencies: List[str]     # ["hostname of device"]
    suggested_source: str       # "Use a system info tool"
```

Raised when the executor's LLM diagnosis determines the tool failed because a required
runtime value (not in the schema) was missing.

### 8.2 Resolution Flow

```
Tool execution fails → MissingDependencyError
          │
          ▼
Build context from error.dependencies
          │
          ▼
Nested select_tools() with mode="evidence"
  ticket_text="Need to discover: {dependencies}"
          │
          ▼
Execute best fully-bindable resolution tool
          │
          ▼
LLM extracts missing values from resolution output
          │
          ▼
Rebind failed tool with resolved args
          │
          ▼
Agent retries original tool (max 1 attempt)
```

### 8.3 Constraints

- Single-depth only — resolution tools cannot trigger further resolution
- One retry attempt for the original tool after resolution

---

## 9. Tool Indexing Pipeline

**File**: `src/core/registry.py`
**Method**: `CapabilityRegistry.index_tools()` (line 225)
**Triggered**: at API startup (lifespan) and in `run_mock.py`

### 9.1 Flow

```
 MCP Servers (config)           Builtin Packs (plugins/)
        │                              │
        ▼                              ▼
 MCPClient.discover_tools()    load_builtin_packs()
        │                              │
        └──────────┬───────────────────┘
                   ▼
        CapabilityRegistry._tools (dict)
                   │
                   ▼
        index_tools()
                   │
        ┌──────────┴──────────┐
        │ Diff check:         │
        │ get_indexed_tool_   │
        │ names() from Qdrant │
        │ vs _tools.keys()    │
        └──────────┬──────────┘
                   │ (only NEW tools)
                   ▼
        For each new tool:
          1. _extract_tool_metadata()
             → vendor, method, read_only,
               category, param_count
          2. Build embed_text:
             "{description}. Parameters:
              param1 (required): desc;
              param2 (optional): desc; ..."
          3. Build metadata dict
                   │
                   ▼
        vector_store.batch_index_tools(
           texts, metadatas, ids,
           customer_id="__global__"
        )
                   │
                   ▼
        Qdrant tool_catalog collection
          (OpenAI 1536-dim vectors)
```

### 9.2 Metadata Extraction (`_extract_tool_metadata`, line 55)

| Field | Strategy |
|---|---|
| `vendor` | 1. Config: `MCP_SERVER_VENDOR_MAP[server_name]`<br>2. Pattern match: scan tool name for known vendor keywords (fortinet, cisco, paloalto, aws, azure, gcp, vmware, kubernetes, etc.) |
| `method` | Prefix match: `get_*`, `post_*`, `put_*`, `delete_*`<br>Suffix match: `*_get`, `*_post`<br>Embedded: `_get_`, `_read_`, `_list_`, `_show_` |
| `read_only` | `True` if method is "get" OR description doesn't start with mutating verbs (create, update, delete, modify, set, configure, etc.) |
| `category` | Keyword scan on `f"{name_lower} {desc_lower}"` against predefined categories: routing, policy, interface, performance, logs, config, status, inventory, session, certificate, dns, user, container, database, storage, network |
| `param_count` | Length of `required` fields in JSON schema |

### 9.3 Embed Text Format

The text that gets embedded (vectorized) per tool:

```
"Check routing table entries for a FortiGate device. Parameters:
 device (required): target device hostname or IP;
 vdom (optional): virtual domain name;
 limit (optional): maximum number of entries to return"
```

---

## 10. Qdrant Tool Catalog Schema

**Collection**: `tool_catalog`
**Vector**: 1536 dimensions (OpenAI text-embedding-3-small), COSINE distance

### 10.1 Payload Fields

| Field | Type | Source | Purpose |
|---|---|---|---|
| `tool_name` | KEYWORD | `tool.name` | Unique tool identifier |
| `description` | TEXT | `tool.description` | Human-readable description |
| `server_name` | KEYWORD | MCP server name | Which server provides this tool |
| `args_schema` | JSON | `tool.args_schema` | Full JSON schema for arguments |
| `vendor` | KEYWORD | Extracted (see 9.2) | e.g. "fortinet", "cisco", "generic" |
| `method` | KEYWORD | Extracted | "get", "post", "unknown" |
| `read_only` | KEYWORD | Extracted | "true" or "false" (string) |
| `category` | KEYWORD | Extracted | "routing", "policy", "config", etc. |
| `param_count` | INTEGER | Extracted | Number of required params |
| `customer_id` | KEYWORD | Always `"__global__"` | Global catalog, shared across tenants |
| `source_type` | KEYWORD | Always `"tool_catalog"` | Collection type tag |
| `page_content` | TEXT | Embed text | Description + param summary |
| `created_at` | TEXT | ISO timestamp | Indexing time |

### 10.2 Indexed Fields (Qdrant Payload Indexes)

```
customer_id  (KEYWORD, is_tenant=True)
tool_name    (KEYWORD)
server_name  (KEYWORD)
vendor       (KEYWORD)
method       (KEYWORD)
read_only    (KEYWORD)
category     (KEYWORD)
source_type  (KEYWORD)
```

---

## 11. Execution & Adaptive Healing

**File**: `src/core/adaptive_executor.py`
**Class**: `AdaptiveExecutor`

### 11.1 Execution Flow

```
AdaptiveExecutor.execute(tool, args, context, intent)
          │
          ├─ Try 1: tool.run(**args)
          │    ├─ Success + substantial output → return result
          │    ├─ Soft failure (short output + error keywords) → retry
          │    └─ Exception → retry
          │
          ├─ On retry: _diagnose_and_fix()
          │    ├─ RAG: query adaptive_fixes KB for prior fixes
          │    ├─ LLM: diagnose error, propose fixed args
          │    │    ├─ Returns {"args": {...}} → retry with fixed args
          │    │    └─ Returns {"missing_info": [...]} → MissingDependencyError
          │    └─ Langfuse tracing
          │
          ├─ Try 2: tool.run(**fixed_args)
          │    ├─ Success → _learn_from_recovery() → save fix to KB
          │    └─ Failure → give up, return error
          │
          └─ Audit: _log_tool_call() → ToolCallAuditORM (PostgreSQL)
```

### 11.2 Key Parameters

- **Max retries**: 2 (or 1 in `TEST_MODE_FAST`)
- **Soft failure detection**: output < 500 chars AND contains error keywords
- **Learning**: on successful recovery, saves (bad_args, good_args, insight) to `adaptive_fixes` collection

---

## 12. Safety & Governance

### 12.1 Three Safety Layers

```
Layer 1: Keyword Blocking         (src/core/safety.py → is_safe_tool)
  Checks tool name + all arg values against SAFETY_BLOCKED_KEYWORDS
  Blocks: sniffer, packet capture, execute, delete, shutdown, etc.
          │
          ▼
Layer 2: Registry Safety Filter   (src/core/registry.py → _is_safe)
  Applied during Phase 2 candidate construction
  Same keyword check against tool name
          │
          ▼
Layer 3: Tenant Governance        (src/core/safety.py → is_tool_allowed_for_tenant)
  Checks CapabilityScope ORM table for allowed_tools patterns per tenant
  Uses fnmatch wildcards (e.g., "get_*", "*_read")
  Fallback: if no scopes defined → allow all
```

### 12.2 Enforcement Points

| Location | File | Line | Check |
|---|---|---|---|
| Phase 2: candidate construction | `tool_selector.py` | 147 | `_is_safe(t_name)` |
| Pre-execution (evidence_collector) | `evidence_collector.py` | 134 | `is_safe_tool(name, args)` |
| Pre-execution (evidence_collector) | `evidence_collector.py` | 139 | `is_tool_allowed_for_tenant()` |
| Pre-execution (investigator) | `investigator.py` | ~140 | Same checks |

### 12.3 Blocked Keywords (from `config.py`)

```
Execution: debug flow, sniffer, packet capture, pcap, tcpdump,
           wireshark, execute, configure, set, edit, delete, rm,
           shutdown, reboot
Data:      drop database, truncate, format, destroy, purge, kill
Deploy:    deploy, push, publish, migrate, alter, grant, revoke
```

---

## 13. Worked Example

**Scenario**: Ticket — "Users on subnet 192.168.241.0 cannot reach AWS homepage through FortiGate FW-01"

### Step 1: Agent Creates Context

```python
# evidence_collector, processing component FW-01
ctx = ToolSelectionContext(
    ticket_text="Users on subnet 192.168.241.0 cannot reach AWS ...",
    component=Component(id="FW-01", role="firewall", vendor="Fortinet"),
    components=[Component(id="FW-01", ...), Component(id="AWS-GW", ...)],
    facts={"subnet": "192.168.241.0"},
    mode="evidence",
)
```

### Step 2: Phase 1 — Intent Generation

LLM receives evidence intent prompt. Produces:

```json
{"intents": ["firewall routing table", "firewall policy rules", "firewall interface status"]}
```

→ `[ToolIntent(query="firewall routing table"), ToolIntent(query="firewall policy rules"), ToolIntent(query="firewall interface status")]`

### Step 3: Phase 2 — Semantic Retrieval

For each intent, Qdrant is searched with `vendor="fortinet"`, `read_only=True`:

```
Intent "firewall routing table":
  → fortinet_rtm_routes_get       (score: 0.89)
  → fortinet_rtm_route_lookup     (score: 0.85)
  → generic_routing_show_table    (score: 0.72)

Intent "firewall policy rules":
  → fortinet_fwp_policies_get     (score: 0.91)
  → fortinet_fwp_policy_lookup    (score: 0.84)

Intent "firewall interface status":
  → fortinet_nwi_interfaces_get   (score: 0.88)
  → fortinet_nwi_interface_detail (score: 0.82)
```

After dedup: 7 unique candidates.

### Step 4: Phase 3 — Per-Tool Evaluation

LLM evaluates batch of 5, then batch of 2:

```json
[
  {"tool_name": "fortinet_rtm_routes_get",    "relevant": true,  "priority": 1, "reasoning": "Routing table reveals path to destination — critical for connectivity issue"},
  {"tool_name": "fortinet_fwp_policies_get",  "relevant": true,  "priority": 1, "reasoning": "Firewall policies may be blocking traffic to AWS"},
  {"tool_name": "fortinet_nwi_interfaces_get","relevant": true,  "priority": 2, "reasoning": "Interface status confirms link is up"},
  {"tool_name": "fortinet_rtm_route_lookup",  "relevant": false, "priority": 0, "reasoning": "Redundant with routing table dump"},
  {"tool_name": "generic_routing_show_table", "relevant": false, "priority": 0, "reasoning": "Vendor-specific tool available; generic unnecessary"},
  {"tool_name": "fortinet_fwp_policy_lookup", "relevant": true,  "priority": 3, "reasoning": "Useful for targeted policy check if general list is too broad"},
  {"tool_name": "fortinet_nwi_interface_detail","relevant": false,"priority": 0, "reasoning": "Interface list sufficient for initial triage"}
]
```

Approved (sorted by priority): `fortinet_rtm_routes_get` (1), `fortinet_fwp_policies_get` (1), `fortinet_nwi_interfaces_get` (2), `fortinet_fwp_policy_lookup` (3)

### Step 5: Phase 4 — Argument Binding

LLM receives component metadata, ticket text, facts, tool schemas. Returns:

```json
[
  {"name": "fortinet_rtm_routes_get",    "args": {"device": "FW-01", "vdom": "root", "limit": 100}},
  {"name": "fortinet_fwp_policies_get",  "args": {"device": "FW-01", "vdom": "root"}},
  {"name": "fortinet_nwi_interfaces_get","args": {"device": "FW-01"}}
]
```

Note: `fortinet_fwp_policy_lookup` was omitted by LLM. Three-tier recovery:
- Has required params (`device`, `policy_name`)? → Yes
- All operational? → No (`policy_name` is contextual)
- → Tier 3: trust LLM omission. Not recovered.

Deterministic check: `fortinet_rtm_routes_get` has `vdom` as required.
If `vdom` was NOT in args → `missing_params = {"vdom": "Virtual domain name"}`.
In this example, LLM correctly bound `vdom="root"` → no missing params.

### Step 6: Execution

```
fortinet_rtm_routes_get(device="FW-01", vdom="root", limit=100)
  → Dedup check: "fortinet_rtm_routes_get::a1b2c3d4" — new → proceed
  → Safety check: pass
  → Governance check: pass
  → AdaptiveExecutor.execute() → returns routing table text
  → EvidenceStore.save_evidence() → EvidenceSnapshot

fortinet_fwp_policies_get(device="FW-01", vdom="root")
  → ... same flow ...

fortinet_nwi_interfaces_get(device="FW-01")
  → ... same flow ...
```

Result: 3 `EvidenceSnapshot` objects added to `state["evidence_refs"]`.

---

## 14. Configuration Parameters

| Parameter | Default | File | Purpose |
|---|---|---|---|
| `EMBEDDING_MODEL` | `"text-embedding-3-small"` | `config.py:27` | OpenAI embedding model |
| `EMBEDDING_DIMENSIONS` | `1536` | `config.py:28` | Vector size |
| `EMBEDDING_BATCH_SIZE` | `64` | `config.py:29` | Embeddings per API call |
| `QDRANT_SCORE_TOOL_CATALOG` | `0.15` | `config.py:37` | Minimum cosine similarity for tool search |
| `QDRANT_HNSW_EF` | `128` | `config.py:32` | Search depth parameter |
| `QDRANT_HYBRID_ENABLED` | `False` | `config.py` | Enable BM25 + dense hybrid search |
| `MCP_SERVER_VENDOR_MAP` | `{}` | `config.py:64` | Manual server → vendor mapping |
| `SAFETY_BLOCKED_KEYWORDS` | `[list]` | `config.py:107-118` | Blocked mutation/destructive keywords |
| `TEST_MODE_FAST` | `False` | `config.py:11` | Reduces retries + limits |
| Max intents | `3` | `tool_selector.py:44` | Per select_tools() call |
| Candidates per intent | `10` | `tool_selector.py:45` | Qdrant search limit |
| Evaluation batch size | `5` | `tool_selector.py:222` | Tools per LLM eval call |
| Max prereqs | `2` | `tool_selector.py:545` | Prerequisite resolution cap |
| Executor retries | `2` | `adaptive_executor.py` | Max retry attempts |
| Facts in binding | `30` | `tool_selector.py:392` | Max facts shown to binding LLM |
| Evidence in binding | `2000 chars` | `tool_selector.py:384` | Max evidence context length |

---

## 15. File Reference

| File | Key Functions | Role |
|---|---|---|
| `src/core/tool_selector.py` | `select_tools()`, `generate_intents()`, `retrieve_candidates()`, `evaluate_candidates()`, `_evaluate_batch()`, `bind_arguments()`, `resolve_prerequisites()`, `resolve_runtime_dependency()`, `_build_evidence_intent_prompt()`, `_build_investigation_intent_prompt()`, `_build_relational_intent_prompt()`, `_fallback_intents()`, `_get_brute_force_candidates()`, `_classify_params_as_operational()`, `_format_component_for_binding()`, `_rebind_with_prereq_data()` | Central 4-phase pipeline |
| `src/core/registry.py` | `index_tools()`, `_extract_tool_metadata()`, `list_tools()`, `get_tool()`, `load_external_tools()`, `semantic_search_tools()` | Tool registration + indexing |
| `src/core/qdrant.py` | `search_tool_catalog()`, `batch_index_tools()`, `search()`, `get_tool_insights()`, `ensure_all_collections()` | Vector store (Qdrant) |
| `src/core/adaptive_executor.py` | `execute()`, `_diagnose_and_fix()`, `_learn_from_recovery()`, `_log_tool_call()` | Execution + self-healing |
| `src/core/safety.py` | `is_safe_tool()`, `is_tool_allowed_for_tenant()` | Safety + governance |
| `src/core/evidence_store.py` | `save_evidence()` | Immutable evidence snapshots |
| `src/agents/evidence_collector.py` | `evidence_collector_node()`, `_collect_relational_evidence()`, `_is_relational_ticket()` | Evidence collection agent |
| `src/agents/investigator.py` | `investigator_agent_node()` | Hypothesis verification agent |
| `src/core/models.py` | `ToolIntent`, `ToolCandidate`, `ToolEvaluation`, `ToolSelection`, `ToolSelectionContext`, `Component`, `Hypothesis` | Data models |
| `src/config.py` | Settings class | All configuration tunables |
| `src/mcp/client.py` | `MCPClient`, `ExternalToolWrapper` | MCP server discovery + execution |
| `src/core/llm.py` | `LLMFactory` | LLM instance management |

---

## Appendix: Data Model Relationships

```
ToolSelectionContext
  ├── ticket_text: str
  ├── component: Component           ◄── current component being investigated
  ├── components: List[Component]    ◄── all ticket components
  ├── hypothesis: Hypothesis         ◄── (investigation mode only)
  ├── source_component: Component    ◄── (relational mode only)
  ├── target_component: Component    ◄── (relational mode only)
  ├── facts: Dict[str, Any]
  ├── path_context: str              ◄── evidence gaps from path_analysis
  ├── evidence_summaries: str
  └── mode: str                      ◄── "evidence" | "investigation" | "relational"

ToolIntent
  ├── query: str                     ◄── "firewall routing table"
  └── goal: str                      ◄── optional explanation

ToolCandidate
  ├── tool_name: str
  ├── description: str
  ├── args_schema: dict              ◄── full JSON schema
  ├── search_score: float            ◄── Qdrant cosine similarity
  ├── source_intent: str
  ├── catalog_context: str
  ├── vendor, method, read_only, category, param_count

ToolEvaluation
  ├── tool_name: str
  ├── relevant: bool
  ├── reasoning: str
  └── priority: int

ToolSelection
  ├── name: str
  ├── args: Dict[str, Any]           ◄── bound arguments
  ├── evaluation: ToolEvaluation
  └── missing_params: Dict[str, str] ◄── unbound required params
```
