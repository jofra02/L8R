> Historical design blueprint — superseded. The control-plane/data-plane split and the tenant-isolation maxims informed the current schema; the DB-per-tenant option discussed below was not adopted (shared PostgreSQL with `customer_id` FK isolation shipped instead). Current doc: [Data Layer](../../architecture/data_layer.md).

# Support AI Agent Framework (L1/L2) — Data Layer Blueprint (PostgreSQL + Qdrant)

**Fecha:** 2026-02-16  
**Fuente de requisitos:** `README.md` + `multiagent_framework_v2.md` (evidence-first, read-only, multi-tenant).  
**Suposiciones:** PostgreSQL 16, Qdrant 1.16.x, Docker/Compose como runtime base.

---

## 1) Principios no negociables (maximas)

1) **`customer_id` obligatorio** en el `State` y en cada request de la API.  
   - Si falta: **fail-closed** (HTTP 400/401) antes de tocar cualquier store.
2) **Evidence-first, read-only:** el sistema **no ejecuta cambios** (no `config`, no `set`, no `delete`, no `exec`).  
   - Toda afirmación importante debe apuntar a evidencia (artefacto inmutable + hash).
3) **Aislamiento fuerte por tenant:** “no mezclar contextos” es un requisito de seguridad, no de conveniencia.
4) **Defense-in-depth:** incluso si hacés DB-per-tenant, mantené `customer_id` en el State, en auditoría y en payloads (sirve para guardrails + migraciones futuras).
5) **Nada de secretos persistidos:** tokens/PSKs/passwords siempre redacted antes de loguear o persistir.
6) **Observabilidad obligatoria:** `trace_id` por ticket + auditoría de tool-calls + “case file” exportable.

> En el framework ya aparecen como requerimientos: `customer_id` source of truth, versionado de contexto, audit logging y tenant binding por tool-call.

---

## 2) Decisión: ¿DB (Docker) por cliente es recomendable?

### Sí, **si** cumplís estas condiciones
- **Pocos clientes** (ej. 1–20/30) o crecimiento moderado y controlado.
- Necesitás **aislamiento operacional/físico** (compliance, contratos, clientes grandes).
- Querés reducir al mínimo el riesgo de bug de filtrado y simplificar debugging (“este contenedor es ACME”).

### No, **si** esperás escala alta (decenas/centenas) sin automatización fuerte
- Operación se vuelve pesada: upgrades, migrations, backups, snapshots, monitoreo, rotación de credenciales.
- “N tenants = N stacks” exige **provisioning & lifecycle management** serio (IaC + pipeline).

### Recomendación práctica
- **Arranque**: DB-per-tenant (como querés), pero con arquitectura **control-plane / data-plane** (abajo).  
- **Evolución**: cuando el número de clientes suba o quieras eficiencia, migrás a **shared Postgres + RLS** y/o **Qdrant multi-tenant** sin reescribir todo (porque ya mantenías `customer_id` y wrappers).

---

## 3) Arquitectura recomendada (para DB-per-tenant sin mezclar contextos)

### 3.1 Control Plane (global / shared)
Un store global mínimo para **routing** y **estado del tenant**.

**`platform_db` (Postgres)**
- `tenants`: `customer_id`, `name`, `status`, `plan`, `created_at`
- `tenant_endpoints`: `customer_id`, `pg_dsn_ref`, `qdrant_url_ref`, `object_store_ref`
- `capability_scopes`: allowlist de tools por tenant, quotas, rate limits
- `key_management_refs`: referencias a secretos (Vault/SM), **no** secretos

**Por qué existe**
- La API recibe `customer_id` → resuelve “a qué stack conectar” → valida status/allowlist → ejecuta.

### 3.2 Data Plane (por tenant)
Un “Tenant Stack” por cliente:

- `tenant_pg` (Postgres): tickets, runs, auditoría, evidencia, contexto, referencias a vectores
- `tenant_qdrant` (Qdrant): embeddings del tenant (KB, baselines, inventory docs, artefactos resumidos)
- `tenant_object_store` (MinIO/S3): blobs grandes de evidencia (exports, logs, configs)

### 3.3 Guardrails anti-mix
1) Resolver tenant vía control-plane **antes** de abrir conexiones.
2) Al iniciar un run: escribir `run.customer_id` en Postgres y validar que coincida con el request.
3) Wrappers únicos:
   - `PgStore.for_customer(customer_id)`
   - `VectorStore.for_customer(customer_id)`
4) En Qdrant payload: `customer_id` igual (aunque el Qdrant sea exclusivo), para poder auditar inconsistencias.

---

## 4) Postgres: esquema data-plane (por tenant)

### 4.1 Entidades principales (alineadas al State y al pipeline)

**tickets**
- `id` (uuid, pk)
- `external_id` (text, nullable)
- `mode` (enum: incident|change)
- `severity` (enum)
- `text` (text)
- `source` (text)
- `raw_payload` (jsonb)
- `opened_at`, `created_at`

**agent_runs**
- `id` (uuid, pk)
- `ticket_id` (fk tickets)
- `trace_id` (text, unique)
- `status` (enum)
- `state_json` (jsonb)  ← snapshot del State (sin secretos)
- `started_at`, `ended_at`
- `cost_json` (jsonb)

**agent_events** (pasos/nodos LangGraph)
- `id` (bigserial, pk)
- `run_id` (fk agent_runs)
- `seq` (int)
- `node` (text)
- `input_json`, `output_json`, `llm_meta_json` (jsonb)
- `created_at`

**tool_calls_audit** (MCP tool-call audit)
- `id` (uuid, pk)
- `run_id` (fk agent_runs)
- `tool_name` (text)
- `args_redacted` (jsonb)
- `result_meta` (jsonb)  (status code, sizes, timings)
- `status` (enum)
- `started_at`, `ended_at`
- `error` (text)

**evidence_artifacts** (inmutable, referenciable)
- `id` (uuid, pk)
- `run_id` (fk agent_runs)
- `tool_call_id` (fk tool_calls_audit, nullable)
- `sha256` (text, unique)  ← dedupe
- `content_type` (text)
- `size_bytes` (bigint)
- `storage_uri` (text)     ← S3/MinIO URI
- `summary` (text)
- `created_at`

**facts_normalized**
- `id` (uuid, pk)
- `run_id` (fk agent_runs)
- `kind` (text)            ← Common Evidence Model
- `data` (jsonb)
- `sources` (uuid[])       ← evidence_artifacts ids
- `created_at`

**hypotheses**
- `id` (uuid, pk)
- `run_id` (fk agent_runs)
- `summary` (text)
- `confidence` (real)
- `required_facts` (jsonb)
- `supporting_refs` (jsonb)
- `disconfirming_refs` (jsonb)
- `next_playbooks` (text[])
- `created_at`

**plans**
- `id` (uuid, pk)
- `run_id` (fk agent_runs)
- `plan_json` (jsonb)      ← diagnosis_steps, proposed_changes, validation, rollback
- `created_at`

**client_context_versions**
- `id` (uuid, pk)
- `version` (text)         ← semver o timestamped
- `inventory` (jsonb)
- `dependencies` (jsonb)
- `baselines` (jsonb)
- `known_changes` (jsonb)
- `access_scopes` (jsonb)
- `created_at`

**knowledge_docs** (lo que embebés)
- `id` (uuid, pk)
- `doc_type` (text)        ← kb|baseline|inventory|runbook|evidence_summary
- `title` (text)
- `text` (text)
- `metadata` (jsonb)
- `sha256` (text, unique)
- `created_at`
- `deleted_at` (nullable)

**vector_refs** (puente Postgres ↔ Qdrant)
- `id` (uuid, pk)
- `doc_id` (fk knowledge_docs)
- `qdrant_collection` (text)
- `point_id` (uuid/text)
- `embedding_model` (text)
- `chunk_id` (int)
- `sha256` (text)
- `created_at`

### 4.2 Índices mínimos (operables)
- `tickets(created_at)`, `tickets(mode, severity)`
- `agent_runs(ticket_id)`, `agent_runs(trace_id unique)`, `agent_runs(started_at)`
- `agent_events(run_id, seq)`, `agent_events(created_at)`
- `tool_calls_audit(run_id)`, `tool_calls_audit(tool_name, status)`, `tool_calls_audit(started_at)`
- `evidence_artifacts(sha256 unique)`, `evidence_artifacts(run_id)`, `evidence_artifacts(created_at)`
- `knowledge_docs(sha256 unique)`, `knowledge_docs(doc_type, created_at)`
- `vector_refs(doc_id, chunk_id)`, `vector_refs(point_id)`

### 4.3 Particionado (cuando empiece a doler)
- `agent_events` y `tool_calls_audit`: partition por mes (`created_at`) para retención rápida y queries baratas.
- `evidence_artifacts`: mantener metadata en PG; blobs en object storage.

### 4.4 Retención (sugerida)
- `agent_events/tool_calls_audit`: 30–90 días (según compliance).
- `agent_runs/state_json`: 90–180 días o export a “case file”.
- `evidence_artifacts`: depende del cliente; por default 90 días + snapshots.

---

## 5) Qdrant: diseño data-plane (por tenant)

### 5.1 Colecciones
Una colección por **embedding model** (dimensionalidad), por ejemplo:
- `support_docs__768`
- `support_docs__3072`

> Mantener “1 colección por modelo” evita mezclar dims y simplifica reindex.

### 5.2 Payload recomendado (aunque sea single-tenant)
- `customer_id` (keyword)
- `doc_id` (keyword)
- `doc_type` (keyword)
- `chunk_id` (int/keyword)
- `source` (keyword)
- `created_at` (keyword)
- `sha256` (keyword)

### 5.3 Indexes en payload
Crear índice para campos que usás en filtros (`doc_type`, `sha256`, `source`, `customer_id`).

### 5.4 Config de rendimiento (si algún día querés multi-tenant en una sola colección)
Qdrant sugiere multi-tenancy por payload y optimización HNSW:
- `payload_m=16` y `m=0` (evita índice global)  
- índice keyword con `is_tenant=true` en `group_id/customer_id`

(En single-tenant esto no es crítico; en shared multi-tenant sí.)

### 5.5 Dedupe / idempotencia
- Usar `point_id = sha256` (o uuid determinístico) para upserts idempotentes.
- Registrar el mapping en `vector_refs`.

---

## 6) “No mezclar contextos”: enforcement en runtime

### 6.1 Contrato de request
Todas las entradas deben incluir:
- `customer_id`
- `ticket` (id/mode/text)
- opcional: `component_refs` (si viene de un webhook)

### 6.2 Validaciones obligatorias (fail-closed)
- `customer_id` existe y está `active` (control-plane)
- tool allowlist por tenant (`access_scopes`)
- `component_id` pertenece al tenant (inventory/context)
- tool-call schema válido (input/output)
- redaction aplicada antes de persistir

### 6.3 Wrapper pattern (único punto de acceso)
- `TenantRouter.resolve(customer_id) -> {pg_pool, qdrant_client, object_store}`
- Bloquear cualquier acceso directo a clients globales sin tenant.

---

## 7) Operación (lo que suele romper en producción)

### 7.1 Provisioning por tenant (automatizar desde el día 1)
- `docker compose up` por tenant con nombres/labels estándar
- credentials únicas por tenant
- healthchecks + readiness
- migration job (Alembic) al levantar

### 7.2 Migrations (Alembic)
- Mismo repo/migrations para todos los tenants.
- Pipeline que itera tenants activos y aplica migrations.
- Si falla un tenant: aislar, no bloquear el resto.

### 7.3 Backups
**Postgres**
- base: `pg_dump` programado
- mejor: WAL + PITR (si el cliente lo paga)

**Qdrant**
- snapshots por colección (export tar)
- en cluster: snapshots por nodo/colección según doc

**Object store**
- versioning + lifecycle rules (retención)

### 7.4 Observabilidad
- logs con `trace_id`, `customer_id`, `run_id`
- métricas: tool-call latency, failure rate, tokens, loops
- alertas: spikes de tool failures, timeouts, crecimiento de storage

---

## 8) Plan de implementación (camino mínimo)

1) Implementar `platform_db` con `tenants` + `tenant_endpoints`.
2) Implementar `TenantRouter` y wrappers (PG/Qdrant/S3).
3) Crear el esquema data-plane (por tenant) + migrations.
4) Implementar `Evidence Store`:
   - save artifact (hash + uri + metadata)
   - redaction + size limits
5) Implementar `knowledge_docs` + pipeline de chunk/embedding + `vector_refs`.
6) Tests “anti-mix”:
   - generar 2 tenants con docs distintos
   - asegurar que queries nunca cruzan (unit + integration).

---

## 9) Alternativa futura: shared Postgres + RLS / shared Qdrant multi-tenant

Si más adelante querés consolidar:
- Postgres: `tenant_id` en todas las tablas + RLS + `SET LOCAL app.tenant_id` por transacción.
- Qdrant: una colección por modelo + `group_id/customer_id` en payload + filtro obligatorio + `is_tenant=true`.

Esto te baja costo operativo y escala mejor, pero exige disciplina de filtros/wrappers.

---

## 10) Checklist para el Dev Agent (qué evaluar)

- [ ] ¿Cuántos tenants esperados (12m) y qué SLA? (define si DB-per-tenant escala)
- [ ] ¿Existe control-plane mínimo para routing y estado del tenant?
- [ ] ¿Wrappers únicos (no acceso directo a stores)?
- [ ] ¿Evidence inmutable con hash + object storage?
- [ ] ¿Redaction garantizada en tool-call logs y state snapshots?
- [ ] ¿Migrations/backup/snapshots automatizados?
- [ ] ¿Test suite anti-mix (2 tenants, 2 datasets) + regression?

---
