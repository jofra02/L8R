# Multi-Agent L1/L2 Tech Framework (Vendor-agnostic, Read-only, Context-aware)

> Objetivo: diseñar e implementar un ecosistema multi-agent (sobre LangGraph) que atienda tickets técnicos (Incident + Change/Implementation), recolecte evidencia **read-only** vía MCP, genere hipótesis y entregue un **plan** (diagnóstico + config delta sugerida + validación + rollback) sin ejecutar cambios.

---

## 0) Supuestos y restricciones
- Stack objetivo: **LangGraph** (Python) + **MCP** (tools) + storage (SQL + object store + vector store).
- El sistema **NO** aplica cambios en infraestructura. Solo:
  - Lee configs/estado/logs
  - Propone hipótesis
  - Propone acciones/configs a realizar (por humano o pipeline externo)
- Acceso a infra por MCP: **superadmin-readonly** con allowlist estricta.
- Multi-tenant: cada cliente tiene su **ClientContext** separado y versionado.

---

## 1) Principios de diseño
- **Vendor-agnostic por contrato**: core no conoce vendors; vendors se agregan como plugins (tools + playbooks + normalizadores).
- **Modularidad total**:
  - Separar: contexto, recolección de evidencia, razonamiento, output
  - Artefactos versionables: playbooks, hypothesis templates, query templates, normalizers
- **Read-only by default** (hard enforcement): tools MCP no exponen operaciones mutantes.
- **Evidence-driven**: no “inventar” inventory/topology; si falta, se declara como `missing_info`.
- **Operabilidad**: cada tool-call auditada; outputs reproducibles; trace por ticket.

---

## 2) Taxonomía de tickets (2 modos)

### 2.1 Incident (algo anda mal)
- Input: síntomas + impacto + timestamp + entorno
- Output:
  - hipótesis rankeadas + evidencia
  - plan de diagnóstico y resolución (sin ejecutar)
  - pasos de validación + rollback propuesto

### 2.2 Change / New Implementation (algo a implementar/modificar)
- Input: requerimientos + constraints + estado actual
- Output:
  - diseño propuesto (opciones + tradeoffs)
  - config delta exacta sugerida (comandos/objetos/policies)
  - validación + rollback

---

## 3) Visión general del ecosistema

```text
[TICKET] -> [Supervisor Graph]
              |
              +--> Context Retrieval (per-customer)
              |
              +--> Classify + Scope Mapping
              |
              +--> Evidence Collection (playbooks, read-only MCP)
              |
              +--> Hypotheses + Ranking
              |
              +--> Plan Builder (diagnosis / config delta / validation / rollback)
              |
              +--> Final Response (structured)
                    |
                    +--> Handoff package (para humano / L3 / TAC)
```

---

## 4) Componentes (módulos) y responsabilidades

### 4.1 Core Orchestrator (LangGraph)
- Orquesta nodos y sub-agents.
- Mantiene `State` único y persistente.
- Implementa loops con stop conditions.

**Responsabilidades**
- Routing: Incident vs Change
- Iteración: gap_check -> collect_evidence -> refine_hypotheses
- Control de costos/loops: `max_iterations`, `max_tool_calls`, “no new evidence”

### 4.2 Client Context Service (multi-tenant)
Fuente de verdad del cliente. Se recupera por `customer_id`.

**ClientContext mínimo (estructurado)**
- `inventory`: devices, roles, mgmt endpoints, versiones, tags
- `subnets`: CIDRs, VRFs/VDOMs/zones
- `topology`: enlaces L2/L3, VIPs, tunnels, upstream/downstream
- `key_services`: VPN/SSO/WAF/DNS/etc
- `key_users`: dueños/contacts/on-call
- `baselines`: naming, patrones de policy, logging, hardening
- `known_changes`: cambios recientes / incident history
- `access_scopes`: qué tools están habilitados para ese cliente

**Interfaces**
- `context.get(customer_id) -> ClientContext`
- `context.search(customer_id, query) -> snippets/refs`
- `context.version(customer_id) -> current_version`

### 4.3 Evidence Layer (MCP Tools + Normalization)
Herramientas read-only para recolectar evidencia, más normalizadores a un modelo común.

**Regla**: el core nunca llama “CLI raw” si puede llamar tools semánticas.

**Outputs normalizados**
- `DeviceStatus`, `ConfigSnapshot`, `LogEvents`, `RouteTable`, `PolicySet`, etc.

### 4.4 Playbook Library (vendor-agnostic + vendor-specific)
Playbooks describen **qué recolectar** y **cómo** (pasos read-only).

- Playbooks “agnósticos” se basan en conceptos comunes:
  - conectividad, auth, routing, DNS, TLS, WAF, endpoint posture, etc.
- Playbooks “vendor plugin” traducen esos conceptos a tools concretas.

### 4.5 Hypothesis Engine
Genera y mantiene hipótesis con:
- `required_facts`
- `supporting_facts`
- `disconfirming_facts`
- `confidence`
- `next_playbooks` recomendados

### 4.6 Plan Builder
Arma el plan final según modo:
- Incident: mitigación/probable root cause + config delta sugerida
- Change: diseño + delta + validación + rollback

### 4.7 Output Formatter
Entrega respuesta estándar, lista para pegar en ticket.

---

## 5) Data contracts (State + artefactos versionables)

### 5.1 State (contrato central)
```json
{
  "ticket": { "id": "...", "mode": "incident|change", "text": "...", "severity": "...", "timestamps": {} },
  "customer_id": "...",
  "client_context": { "version": "...", "inventory": [], "subnets": [], "topology": [], "services": [] },

  "classification": { "issue_type": "...", "domain": ["vpn","auth","routing","waf","switching","sdwan","logging"], "confidence": 0.0 },
  "components": [ { "ref": "device/service", "id": "...", "role": "..." } ],

  "facts": { "normalized": {}, "raw_refs": [] },
  "missing_info": [ "..." ],

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

  "final_answer": "...",
  "meta": { "iterations": 0, "tool_calls": 0, "trace_id": "..." }
}
```

### 5.2 Playbook spec (YAML recomendado)
```yaml
id: net_connectivity_baseline
version: 1
mode: readonly
applies_to:
  domains: [networking, routing, vpn]
inputs:
  - customer_id
  - component_ids
steps:
  - tool: inventory.get
    args: { customer_id: "{{customer_id}}" }
    outputs: [inventory]
  - tool: topology.get
    args: { customer_id: "{{customer_id}}" }
    outputs: [topology]
  - tool: device.status
    args: { device_id: "{{component_ids[0]}}", sections: ["interfaces","routes","sessions"] }
    outputs: [device_status]
normalize:
  - mapping: normalize_device_status_v1
```

### 5.3 Hypothesis template spec
```yaml
id: vpn_auth_failure_generic
version: 1
signals:
  - "login fails"
  - "auth timeout"
domains: [vpn, auth]
required_facts:
  - vpn_mode
  - auth_backend
  - recent_changes
playbooks:
  - vpn_baseline_readonly
  - auth_backend_health_readonly
decision_rules:
  - if: "auth_backend == 'SAML' and saml_errors_present"
    then: "increase_confidence"
```

---

## 6) Segmentación de tareas (sub-agents)

### 6.1 Supervisor Agent (router + control)
- Decide modo (incident/change)
- Decide dominios (vpn/auth/routing/etc); puede ser uno o varios
- Controla loops/stop conditions
- Ensambla el “case file” final

### 6.2 Context Agent (per-customer)
- Recupera `ClientContext`
- Detecta gaps de contexto (inventory incompleto, topology faltante)
- Sugiere cómo completar (sin bloquear si se puede avanzar)

### 6.3 Classifier Agent
- Clasifica el ticket a dominios + severidad + señales
- Sugiere componentes probables (basado en context + síntomas)

### 6.4 Scoper/Mapper Agent
- Mapea “partes involucradas” (devices, servicios, usuarios, links)
- Genera `components[]` priorizados

### 6.5 Evidence Collector Agent
- Selecciona playbooks según dominios + hipótesis iniciales
- Ejecuta tools read-only
- Normaliza outputs y adjunta refs

### 6.6 Hypothesis Agent
- Genera hipótesis genéricas al inicio (sin vendor)
- Refina con evidencia y reduce el set (ranking)
- Produce “qué falta para confirmar/refutar”

### 6.7 Planner Agent
- Incident: arma plan de diagnóstico + posibles fixes + validación/rollback
- Change: arma diseño + config delta + validación/rollback

### 6.8 Response Agent
- Redacta respuesta estructurada de ticket
- Produce “handoff package” (para L3/TAC)

---

## 7) MCP Tooling (diseño seguro, multi-tenant)

### 7.1 Reglas obligatorias
- Hard deny mutaciones: no `set`, `config`, `delete`, `exec`.
- Allowlist de endpoints/queries.
- Validación `customer_id -> device_id` pertenencia.
- Redacción de secretos (tokens, PSKs, passwords, private keys).
- Auditoría completa por tool-call.

### 7.2 Conjunto mínimo de tools (agnósticos)
- `context.get(customer_id)`
- `inventory.get(customer_id, filters)`
- `topology.get(customer_id, scope)`
- `device.status(device_id, sections[])`
- `device.config_snapshot(device_id, areas[])`
- `logs.query(customer_id, source, query_template, params)`
- `routing.table(device_id)`
- `policy.read(device_id|scope, filters)`
- `auth.status(scope)` (si aplica)
- `waf.status(scope)` (si aplica)

> Vendors se implementan detrás de estas interfaces (adapter pattern).

---

## 8) Loops y stop conditions (para evitar “agents infinitos”)

**Loop base (Incident)**
1. classify + scope
2. gap_check
3. collect_evidence
4. generate/refine hypotheses
5. si confidence suficiente -> build plan -> respond
6. si no -> pedir info mínima o escalar

**Stop conditions**
- `iterations >= N`
- `tool_calls >= M`
- “no new evidence” en 2 ciclos
- “missing_info bloqueante” sin alternativa

---

## 9) Output estándar (formato ticket)

### 9.1 Incident
- Resumen (1-2 líneas)
- Componentes involucrados
- Evidencia clave (bullets)
- Hipótesis rankeadas (confidence + cómo confirmar)
- Qué habría que tocar (config delta sugerida, sin ejecutar)
- Validación
- Rollback
- Pendientes / info faltante / criterio de escalamiento

### 9.2 Change / Implementation
- Requerimiento interpretado + supuestos
- Estado actual relevante (evidencia)
- Diseño propuesto (opciones + tradeoffs)
- Config delta sugerida
- Validación
- Rollback
- Riesgos y mitigaciones

---

## 10) Plugin model (vendor/product)

Un plugin debe aportar:
1) Adapters MCP para cumplir interfaces agnósticas
2) Normalizers (vendor -> modelo común)
3) Playbooks específicos (recolección)
4) Hypothesis templates específicas (cuando aplique)
5) Query templates (logs / event types) y parsers

Estructura recomendada:
```text
plugins/
  fortinet/
    tools/
    normalizers/
    playbooks/
    hypotheses/
  cisco/
  paloalto/
  generic/
```

---

## 11) MVP (camino mínimo implementable)
1) Implementar `ClientContext` + 1 cliente piloto.
2) Implementar 8-10 tools MCP agnósticos (read-only).
3) Implementar 10 playbooks base (vpn/auth/routing/connectivity/logging/waf).
4) Implementar LangGraph con:
   - Supervisor
   - Context Agent
   - Classifier
   - Evidence Collector
   - Hypothesis Agent
   - Planner
   - Response Agent
5) Logging/auditoría + traces por ticket.
6) Medir: %tickets cerrados, %requiere preguntas, tiempo y tool_calls.

---

## 12) Criterios de aceptación (Definition of Done)
- Multi-tenant real: no cruza contexto entre clientes.
- Todas las tools son read-only y auditadas.
- Respuestas reproducibles: cada claim importante apunta a evidencia (`raw_refs`).
- Hipótesis explícitas con cómo confirmar/refutar.
- Para Change: delta de config claro + validación + rollback.
- Stop conditions funcionando; no loops infinitos.
- Plugins agregables sin tocar el core.

---

## 13) Notas de implementación (recomendaciones)
- Persistencia de State (checkpoints) por ticket para reanudar.
- “Case file” exportable (JSON/MD) para handoff a humano.
- Tests:
  - unit: normalizers, playbook parsing, ranking
  - integration: MCP tools (mock) + graph end-to-end
  - security: deny mutaciones, redaction, tenant isolation
