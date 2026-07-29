# Device Assessments

Deterministic, definition-driven security assessments over managed devices.
First supported target: FortiGate (`fortigate-security-baseline`).

Unlike ticket investigations (where the Engineer ReAct agent decides which
tools to run), an assessment executes a **versioned, pre-defined collection
plan** — the LLM never chooses tools. The LLM participates only in controls
explicitly declared `hybrid`/`llm`, over already-collected evidence, with
schema-validated output and verified citations.

## Architecture

```
YAML definition (src/assessments/definitions/<vendor>/<product>/<name>/<version>.yaml)
   │  DefinitionRegistry.sync_definitions()  — validation + immutable DB snapshot
   ▼
assessment_definition_versions (content JSON + sha256; runs pin a version id)
   │
POST /assessments (draft, targets snapshotted from inventory) → /start
   ▼
AssessmentRunner (asyncio task, task_registry keyed by run id)
   draft → queued → collecting → evaluating → completed | completed_with_errors | failed
   (queued|collecting|evaluating → cancelled; completed* → evaluating on re-evaluate)
   │
   ├─ CollectionEngine  — topo-ordered steps per target, global+per-device
   │    concurrency, retry w/ backoff (connection|timeout only), in-run dedup,
   │    idempotent re-entry, sanitization, raw blob → EvidenceStore,
   │    normalized JSON → assessment_collection_executions
   │    └─ execute_mcp_tool (src/core/mcp_executor.py) with enforce_read_only
   │
   ├─ EvaluationEngine  — per (target, control): rules/parsers first, LLM only
   │    for hybrid/llm; missing required evidence ⇒ insufficient_evidence
   │
   ├─ ScoringEngine     — weighted, versioned; not_applicable / not_evaluated /
   │    insufficient_evidence / error excluded from the denominator; coverage
   │    reported next to every score
   │
   └─ ReportBuilder     — view-independent JSON model → assessment_reports
```

Module layout:

| Path | Responsibility |
|---|---|
| `src/assessments/schema.py` | Pydantic definition format (validates YAML) |
| `src/assessments/registry.py` | Load + validate + snapshot definitions (immutability by content hash) |
| `src/assessments/collector.py` | CollectionEngine |
| `src/assessments/normalizers.py` | Named normalizer registry (`fortigate.cmdb_results`, …) |
| `src/assessments/evaluation/rules.py` | `@register_rule` / `@register_parser` deterministic evaluators |
| `src/assessments/evaluation/llm_evaluator.py` | Hybrid/LLM evaluation (fencing + citation validation) |
| `src/assessments/evaluation/engine.py` | Dispatch + hybrid merge (worse status wins) |
| `src/assessments/evaluation/sanitize.py` | Secret redaction, size caps, injection fencing |
| `src/assessments/scoring.py` | Score + stats |
| `src/assessments/reporting.py` | Report model |
| `src/assessments/runner.py` | State machine, background job, startup stale-run sweep |
| `src/api/routers/assessments.py` | REST API — 12 endpoints across `/assessments` (10) and `/assessment-definitions` (2); permissions `assessments:read`/`assessments:write` |
| `frontend/src/pages/assessments/` | List, creation wizard, live progress, results |

## Security model

- **Read-only, twice**: every call goes through the global safety keyword
  filter AND the strict assessment allowlist (`is_read_only_tool_name`: tool
  name must contain `_get` and no mutating marker). Mutating tools cannot run.
- **Tenant isolation**: all tables use `TenantMixin`; `tenant` is
  framework-injected into every gateway call; API queries filter by
  `auth.customer_id` (cross-tenant ⇒ 404).
- **Untrusted evidence**: device output is sanitized before persistence
  (field redaction from the step's `sanitize` list + always-redacted names +
  `ENC …`/PEM/CLI-secret patterns, 512 KiB cap). For LLM evaluation, evidence
  is fenced with a per-call random boundary; instructions inside evidence are
  never followed; citations must be verbatim substrings of the supplied
  evidence or the verdict is discarded (`insufficient_evidence`).
- **No fabricated verdicts**: LLM parse failure ⇒ `error`; a pass/fail with
  no verifiable citation is discarded; absence of evidence is never `fail`.

## Definition authoring

Definitions live in
`src/assessments/definitions/<vendor>/<product>/<name>/<version>.yaml` and are
synced to the DB at API startup (or via `sync_definitions()`). Startup sync is
best-effort and gated on `ASSESSMENT_ENABLED`: a failure (e.g. DB down) is
logged and does not block boot.

Rules:

1. **Never edit a published version.** The registry compares the semantic
   content hash against the DB snapshot and refuses to sync a changed file
   with the same `assessment.version` — copy the file to a new version.
   Live example: `fortigate-security-baseline` ships `1.0.0` and `1.0.1`;
   1.0.1 supersedes 1.0.0 (identical controls, collection tool names updated
   for the `fgt_* → fgt74_*` pack prefix rename — 1.0.0 references retired
   tool names and its collection steps will fail).
2. Tool names must exist in `mcp_gateway/baseline_tools.txt` (name-freeze)
   and pass the read-only allowlist.
3. Every `normalizer`, `rule` and `parser` name must be registered in code —
   unknown names fail at sync time, not at run time.
4. `required_evidence` / `optional_evidence` of controls and `depends_on` of
   steps must reference declared step ids (schema-validated).

Step fields: `id`, `tool`, `params`, `required`, `depends_on`, `normalizer`,
`timeout_s`, `max_attempts`, `sanitize` (field names to redact).

Control fields: `id`, `title`, `category`, `severity`, `description`,
`required_evidence`, `optional_evidence`, `evaluation`
(`type: rule|parser|llm|hybrid` + `rule`/`parser`/`llm_instructions`),
`params`, `expected_state`, `references`, `remediation.summary`.

## Scoring methodology

```
evaluated     = controls with status pass|warning|fail
score         = Σ(severity_weight × status_credit) / Σ(severity_weight over evaluated) × 100
coverage      = evaluated / (total − not_applicable)
```

Defaults (overridable per definition in the `scoring` block):
weights `critical=10, high=5, medium=2, low=1`; credit
`pass=1.0, warning=0.5, fail=0.0`. `not_applicable`, `not_evaluated`,
`insufficient_evidence` and `error` never enter the denominator — a score
with incomplete coverage is flagged in the UI and the report.

## Adding a vendor / appliance

Zero core changes required:

1. Create `src/assessments/definitions/<vendor>/<product>/<name>/1.0.0.yaml`.
2. Register normalizers for the vendor's payload envelope in
   `normalizers.py` (`@register_normalizer("<vendor>.<name>")`).
3. Register deterministic evaluators in `evaluation/rules.py`
   (`@register_rule` / `@register_parser`, prefixed `<vendor>.`).
4. Ensure the appliance pack exposes the tools through the MCP gateway
   (see `docs/architecture/mcp_gateway.md`).
5. Add fixtures + tests in `src/testing/`.

## Operational notes

- Config knobs (`src/config.py`): `ASSESSMENT_ENABLED`,
  `ASSESSMENT_GLOBAL_CONCURRENCY` (8), `ASSESSMENT_DEVICE_CONCURRENCY` (3),
  `ASSESSMENT_STEP_TIMEOUT_S` (60), `ASSESSMENT_STEP_MAX_ATTEMPTS` (2),
  `ASSESSMENT_MAX_EVIDENCE_BYTES` (512 KiB), `LLM_MODEL_ASSESSMENT_EVALUATOR`.
- Background execution is in-process (`asyncio.create_task` + task registry).
  There is **no crash recovery**: runs left active at startup are marked
  `failed` ("interrupted by service restart"). Evidence already collected is
  kept; a re-run skips steps already `success` for the same run (retry/resume
  is planned hardening).
- Re-evaluation (`POST /assessments/{id}/reevaluate`) re-runs evaluation +
  scoring + report over the stored evidence without touching devices.
- Migration `e6f7a8b9c0d1` creates the six tables and seeds the
  `assessments:read`/`assessments:write` permissions into the system
  profiles: super admin and tenant admin get both, super admin read-only
  gets `assessments:read` only. API keys do NOT get assessment permissions
  (UI/human-driven feature).

## Tests

`uv run pytest` runs the assessment suites (pinned in `pyproject.toml`):
definitions/immutability, collector (retry/dedup/skip/sanitize), evaluation
(rules on sanitized FortiGate fixtures, hybrid merge, citation validation,
prompt-injection resistance), scoring, state machine, API authorization.
Fixtures: `src/testing/fixtures/fortigate/*.json`.
