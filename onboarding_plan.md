# Onboarding & Data Seeding Plan

To fully operationalize the Support AI Agent, we need pipelines to populate the "Blank Slate" databases (PostgreSQL & Qdrant) with customer specific data.

## 1. Client Context Pipeline (PostgreSQL)

**Objective**: Populate the `ClientContextORM` table which drives the `ContextAgent`.

### Strategy: Control Plane First
Per the Blueprint, we must first establish the tenant in the **Control Plane** before seeding data.

**Phase 1: Control Plane (Platform DB)**
Register the tenant and their scopes.

**Source**: `data/tenants/{customer_id}/tenant.yaml`
```yaml
id: "cust_acme_001"
name: "ACME Corp"
status: "active"
plan: "enterprise"
allowed_tools: ["network_*", "logs_read"]
```

**Phase 2: Data Plane (Context)**
Once the tenant is active, seed their specific infrastructure context.

### Strategy: Git-Ops / File-Based Seeding
We will use structured YAML files to define client environments. This allows version control of the infrastructure definitions.

**Source Format** (`data/tenants/{customer_id}/context.yaml`):
```yaml
customer_id: "cust_acme_001"
version: "1.0.0"
inventory:
  - id: "fw-core-01"
    ref: "Core Firewall"
    role: "firewall"
    metadata: { ip: "10.0.1.1", model: "FortiGate 60F" }
  - id: "srv-web-01"
    ref: "Main Web Server"
    role: "server"
    metadata: { ip: "192.168.1.10", os: "Ubuntu 22.04" }
dependencies:
  - source: "srv-web-01"
    target: "fw-core-01"
    type: "connects_to"
baselines:
  - metric: "avg_latency"
    value: "20ms"
access_scopes: ["network_read", "logs_read"]
```

**Pipeline Steps**:
1.  **Script**: `src/utils/seed_context.py`
2.  **Logic**:
    *   Read YAML.
    *   Validate against `ClientContext` Pydantic model.
    *   Connect to Postgres.
    *   Upsert row in `client_contexts` table for `customer_id`.

## 2. Knowledge Base Pipeline (Qdrant)

**Objective**: Populate the Vector Store with unstructured data (PDFs, Docs, Past Tickets) for the `Enricher` and `Hypothesis` agents.

### Strategy: Bulk Loader
A script to ingest a directory of documents, chunk them, and index them with the mandatory `customer_id` payload.

**Source Structure**:
```text
data/tenants/{customer_id}/kb/
  ├── architecture_diagrams.md
  ├── runbooks/
  │   ├── restart_procedures.md
  ├── past_incidents.json
```

**Pipeline Steps**:
1.  **Script**: `src/utils/seed_kb.py`
2.  **Logic**:
    *   Iterate through files.
    *   **Chunking**: Split text into 500-token chunks (overlap 50).
    *   **Embedding**: Use OpenAI (text-embedding-3-small) to generate vectors.
    *   **Upsert**: Push to Qdrant collection `knowledge_base` with payload `{"customer_id": "...", "source": filename, "text": chunk}`.

## 3. Operations

We will expose these via the CLI:

```bash
# 1. Register Tenant (Control Plane)
uv run python src/main.py register-tenant --file data/tenants/cust1/tenant.yaml

# 2. Seed Context (Data Plane)
uv run python src/main.py seed-context --file data/tenants/cust1/context.yaml

# 3. Seed Knowledge Base (Data Plane)
uv run python src/main.py seed-kb --dir data/tenants/cust1/kb/ --customer-id cust1
```
