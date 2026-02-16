# Multi-Agent Ops Framework (Domain-agnostic, Evidence-first, Read-only)

> **Objetivo**: ecosistema multi-agent (LangGraph) para resolver **tickets técnicos** (Incident + Change/Implementation) con enfoque **evidence-first**. Recolecta evidencia vía **MCP tools** (por defecto **read-only**), genera **hypotheses** y entrega un **plan** (diagnóstico + config delta sugerida + validación + rollback) **sin ejecutar cambios**.
>
> **Última revisión**: 2026-02-16

---

## 0) Alcance

### 0.1 In-scope
- Triage L1/L2: comprensión del ticket, scoping, recolección de evidencia, hipótesis, plan, handoff.
- Multi-tenant real (aislamiento fuerte por `customer_id`).
- Tooling estandarizado vía MCP con **allowlist**, **schemas**, **timeouts**, **rate limits**, **auditoría**.
- Output **estructurado** (JSON) + render humano (Markdown).

### 0.2 Out-of-scope (por diseño)
- Ejecución automática de cambios (write actions).  
  *(Puede existir un pipeline externo; este framework sólo entrega un “handoff package” reproducible.)*

---

## 1) Key concepts (abstraídos del “estado del arte”)

1) **Stateful orchestration**: el agente no es “una llamada al LLM”; es un workflow con estado durable (reanudable) y trazable.  
2) **Planner–Executor**: separar “planificación” (qué hacer) de “ejecución” (tool calls), con validación/policies entre ambas.  
3) **Tool-using loops** (ReAct-like): el agente alterna reasoning ↔ tool calls ↔ observation, pero con límites/stop conditions.  
4) **Agentic RAG**: el retrieval (docs/logs/configs) se decide iterativamente según gaps de evidencia; no es un RAG fijo.  
5) **Memory hierarchy**:
   - short-term: estado del ticket/thread
   - long-term: facts/baselines del cliente (controlado, versionado)
   - evidence store: snapshots inmutables (no “memoria conversacional”)
6) **Multi-agent por roles**: dividir tareas (classifier / scoper / collector / hypothesis / planner / responder) reduce error y mejora operabilidad.  
7) **Governance-by-default**: tool surface es la mayor fuente de riesgo; se requiere policy gates, validation estricta y audit logging.

---

## 2) Arquitectura por “planes” (agnóstico de dominio)

```text
[Data Plane]         [Agent Plane]                          [Governance Plane]
- systems/APIs       - LangGraph orchestrator               - RBAC / policies
- logs/configs       - role agents + playbooks              - audit log / traces
- knowledge base     - memory + retrieval                   - secrets mgmt
                     - normalization + scoring              - approvals (HITL)
```

**Regla**: el Agent Plane sólo interactúa con el Data Plane vía Tools (MCP). Nunca “raw access” directo.

---

## 3) Componentes (módulos) y responsabilidades

### 3.1 Core Orchestrator (LangGraph)
- Mantiene `State` persistente por ticket (checkpointing).
- Enruta: Incident vs Change.
- Controla loops: `max_iterations`, `max_tool_calls`, “no_new_evidence”, “missing_info_blocking”.
- Implementa interrupts/HITL (si algún día agregás acciones write en un pipeline externo).

### 3.2 Capability Registry (catálogo de capacidades)
Define “qué sabe hacer el sistema” sin acoplarse al vendor/dominio:
- `tools` disponibles (por tenant/scope)
- `normalizers` (raw → modelo común)
- `playbooks` (qué recolectar y cómo)
- `hypothesis templates`
- `output schemas`

> Esto permite agregar dominios/vendedores sin tocar el core: sólo registrás un “capability pack”.

### 3.3 Client Context Service (multi-tenant)
Fuente de verdad por `customer_id`. Versionado + “baselines” de operación.

**ClientContext mínimo**
- inventory (assets/components + roles + endpoints + versions)
- topology/dependencies (qué depende de qué)
- baselines (naming, hardening, logging expectations, SLOs)
- known changes (change history)
- access scopes (qué tools están habilitados)

### 3.4 Evidence Layer (MCP Tools + Evidence Store)
- Tools semánticas y tipadas.
- Normalización a un **Common Evidence Model**.
- Persistencia de evidencia como snapshots (hash + timestamp + provenance).

**Common Evidence Model (ejemplos)**
- `ComponentStatus`, `ConfigSnapshot`, `LogEvents`, `RouteTable`, `AuthEvents`, `ServiceHealth`, `DependenciesGraph`

### 3.5 Hypothesis Engine
- Mantiene un set de hipótesis con:
  - `required_facts` (qué falta)
  - `supporting_facts` / `disconfirming_facts`
  - `confidence`
  - `next_playbooks`
- Prioriza “qué evidencia recolectar” para confirmar/refutar.

### 3.6 Plan Builder
Produce un plan reproducible:
- Incident: diagnóstico + mitigación sugerida + validación + rollback
- Change: diseño (opciones + tradeoffs) + delta sugerida + validación + rollback

### 3.7 Output Formatter
- Emite JSON estricto (contrato) + Markdown legible para ticket.
- Genera “handoff package” (para L3/TAC/implementador).

---

## 4) Data contracts (State + artefactos versionables)

### 4.1 State (contrato central)
```json
{
  "ticket": {
    "id": "...",
    "mode": "incident|change",
    "text": "...",
    "severity": "low|med|high|critical",
    "timestamps": { "opened_at": "...", "reported_window": "..." }
  },
  "customer_id": "...",

  "client_context": {
    "version": "...",
    "inventory": [],
    "dependencies": [],
    "baselines": [],
    "known_changes": [],
    "access_scopes": []
  },

  "classification": {
    "domains": ["..."],
    "confidence": 0.0,
    "rationale": "..."
  },
  "components": [
    { "ref": "component", "id": "...", "role": "...", "priority": 1 }
  ],

  "facts": {
    "normalized": {},
    "raw_refs": [
      { "tool_call_id": "...", "artifact_id": "...", "summary": "..." }
    ]
  },
  "missing_info": ["..."],

  "hypotheses": [
    {
      "id": "hyp_001",
      "summary": "...",
      "required_facts": ["..."],
      "supporting_facts": ["..."],
      "disconfirming_facts": ["..."],
      "confidence": 0.0,
      "next_playbooks": ["pb_x", "pb_y"]
    }
  ],

  "plan": {
    "diagnosis_steps": [],
    "proposed_changes": [],
    "validation": [],
    "rollback": []
  },

  "handoff": {
    "case_file_artifacts": [],
    "recommended_escalation": { "to": "L3|TAC|Owner", "reason": "..." }
  },

  "meta": {
    "iterations": 0,
    "tool_calls": 0,
    "trace_id": "...",
    "cost": { "tokens_in": 0, "tokens_out": 0 }
  }
}
```

### 4.2 Playbook spec (YAML)
Playbook = “qué recolectar” + “cómo” (tools) + normalización.

```yaml
id: connectivity_baseline
version: 1
mode: readonly
applies_to:
  domains: [connectivity, routing, auth]   # ejemplos; no obliga al core
inputs:
  - customer_id
  - component_ids
steps:
  - tool: inventory.get
    args: { customer_id: "{{customer_id}}" }
    outputs: [inventory]
  - tool: component.status
    args: { component_id: "{{component_ids[0]}}", sections: ["interfaces","routes","health"] }
    outputs: [status]
normalize:
  - mapping: normalize_component_status_v1
artifacts:
  - persist: true
    kind: evidence_snapshot
```

### 4.3 Hypothesis template spec
```yaml
id: auth_failure_generic
version: 1
signals:
  - "login fails"
  - "timeout"
domains: [auth]
required_facts:
  - auth_backend
  - recent_changes
playbooks:
  - auth_baseline_readonly
decision_rules:
  - if: "auth_backend == 'SAML' and saml_errors_present"
    then: "increase_confidence"
```

---

## 5) MCP Tooling (secure-by-default)

### 5.1 Reglas obligatorias (mínimo)
- **Hard deny mutaciones** en este sistema: no `set`, `config`, `delete`, `exec`.
- **Allowlist** de tools por tenant + scope.
- **Schema validation** estricta (Pydantic / JSON Schema) en inputs y outputs.
- **Timeouts + retries** acotados + circuit breaker por tool.
- **Rate limits** por tenant/tool.
- **Tenant binding**: `customer_id` debe validar pertenencia de `component_id`.
- **Secrets redaction** (tokens, PSKs, passwords, keys) antes de persistir artefactos.
- **Audit logging** por tool-call: nombre, args (redacted), timestamps, resultado, tamaño.

### 5.2 Tools “agnósticos” (interfaces mínimas)
- `context.get(customer_id)`
- `inventory.get(customer_id, filters)`
- `dependencies.get(customer_id, scope)`
- `component.status(component_id, sections[])`
- `component.config_snapshot(component_id, areas[])`
- `logs.query(customer_id, source, query_template, params)`
- `policy.read(scope, filters)`
- `service.health(scope)`

> Los vendors/dominios se implementan detrás de estas interfaces (adapter pattern + normalizers).

---

## 6) Multi-agent roles (SOP claro)

### 6.1 Supervisor Agent
- Routing + control (loops/stop conditions).
- Ensambla “case file” y decide escalamiento.

### 6.2 Context Agent
- Recupera ClientContext.
- Gap analysis de contexto (sin bloquear si se puede seguir).

### 6.3 Classifier Agent
- Clasifica dominios y severidad.
- Propone componentes candidatos (por contexto + síntomas).

### 6.4 Scoper/Mapper Agent
- Reduce el espacio de búsqueda: componentes prioritarios + dependencias.

### 6.5 Evidence Collector Agent
- Selecciona playbooks.
- Ejecuta tools read-only.
- Normaliza + persiste artefactos con provenance.

### 6.6 Hypothesis Agent
- Genera/refina hipótesis.
- Produce “qué falta” para confirmar/refutar.

### 6.7 Planner Agent
- Construye plan con pasos verificables.
- Produce delta sugerida (si aplica) + validación + rollback.

### 6.8 Response Agent
- Emite JSON contractual + Markdown para ticket.
- Arma handoff package (L3/TAC).

---

## 7) Loops y stop conditions (evitar “agent infinito”)

**Loop base (Incident)**
1) classify + scope  
2) gap_check (context + evidence)  
3) collect_evidence (playbooks)  
4) refine_hypotheses + rank  
5) si `confidence >= threshold` o “mejor esfuerzo” → build plan → respond  
6) si falta evidencia bloqueante → pedir info mínima / escalar

**Stop conditions**
- `iterations >= N`
- `tool_calls >= M`
- “no_new_evidence” en 2 ciclos
- “missing_info_blocking” sin alternativa
- “policy_denied” repetido (indica mala selección de tools)

---

## 8) Output contracts (para ticket)

### 8.1 Incident (template)
- Resumen (1–2 líneas)
- Componentes involucrados
- Evidencia clave (bullets con refs)
- Hipótesis rankeadas (confidence + cómo confirmar/refutar)
- Plan de diagnóstico (pasos read-only)
- Config delta sugerida (si aplica, sin ejecutar)
- Validación
- Rollback
- Pendientes / info faltante / criterio de escalamiento

### 8.2 Change / Implementation (template)
- Requerimiento interpretado + supuestos
- Estado actual relevante (evidencia)
- Diseño propuesto (opciones + tradeoffs)
- Config delta sugerida
- Validación
- Rollback
- Riesgos + mitigaciones

---

## 9) Observabilidad, reproducibilidad y auditoría
- **Trace por ticket** (`trace_id`) + tool-call logs.
- **Case file exportable** (JSON + artefactos referenciados).
- **Reproducibilidad**: cada claim importante debe apuntar a evidencia (`raw_refs`).
- **Cost controls**: tokens, tool calls, time per phase.

---

## 10) Evaluación y pruebas (agent-grade)

### 10.1 Offline regression suite
- Corpus de tickets etiquetados con expected outcome (close/escalate, plan mínimo, preguntas mínimas).
- Mide: success end-to-end, precisión de scoping, evidencia mínima recolectada, calidad de plan, costo/latencia.

### 10.2 Tool simulation
- Mocks/cassettes para tools (evita flakiness y permite CI).

### 10.3 Adversarial testing
- Indirect prompt injection en logs/docs.
- Output handling: asegurar que outputs del LLM no se ejecutan ni se convierten en queries peligrosas sin validación.

### 10.4 Métricas recomendadas
- Time-to-triage
- Tool calls per ticket
- %tickets resueltos sin preguntas
- %escala correctamente
- “evidence coverage score” (hechos mínimos presentes)

---

## 11) Plugin model (capability packs)

Un pack debe aportar:
1) Adapters MCP (implementan interfaces agnósticas)
2) Normalizers (vendor/domain → Common Evidence Model)
3) Playbooks específicos
4) Hypothesis templates (si aplica)
5) Query templates (logs/events) + parsers

Estructura sugerida:
```text
packs/
  generic/
  vendor_x/
  domain_y/
```

---

## 12) MVP (camino mínimo implementable)
1) `ClientContext` + 1 tenant piloto.
2) 8–10 tools MCP agnósticos (read-only) + audit log.
3) 10 playbooks base (conectividad/auth/routing/logging/health).
4) LangGraph con: Supervisor + Context + Classifier + Collector + Hypothesis + Planner + Response.
5) Evidence store + case file export.
6) Regression suite inicial + mocks.

---

## 13) Definition of Done
- Aislamiento multi-tenant: no cruza contexto ni artefactos.
- Tools **read-only** y auditadas (deny-by-default).
- Output contractual: JSON validado + Markdown.
- Cada claim relevante tiene evidencia referenciable.
- Stop conditions funcionando.
- Capability packs agregables sin tocar el core.
