# Context Agent

> Loads tenant context from the PostgreSQL-backed ContextStore and seeds the initial topology graph from inventory and dependencies.

## Overview

The context agent is the first data-fetching node in the pipeline. It reads the `customer_id` from state, queries the `ContextStore` for the active `ClientContext` record, and returns it along with seeded topology data.

Topology seeding converts inventory items into `TopologyNode` entries and known dependencies into `TopologyEdge` entries. These pre-populated graph elements provide downstream agents (mapper, enricher, hypothesis) with a structural baseline before any tool execution occurs.

If no context is found for the tenant, the agent returns a default empty `ClientContext` and flags `missing_info` with `"client_context_not_found"`. This allows the pipeline to continue with degraded information rather than halting.

## Flow Diagram

```mermaid
flowchart TD
    START([context_agent_node]) --> CID{customer_id present?}
    CID -- No --> ERR[Return missing_info: customer_id]
    CID -- Yes --> QUERY[Query ContextStore.get_active_context]
    QUERY --> FOUND{Context found?}
    FOUND -- Yes --> SEED[Seed topology from inventory + dependencies]
    SEED --> NODES[Inventory items -> TopologyNode entries]
    SEED --> EDGES[Dependencies -> TopologyEdge entries]
    NODES --> RETURN[Return client_context + topology_nodes + topology_edges]
    EDGES --> RETURN
    FOUND -- No --> DEFAULT[Return default empty ClientContext + missing_info]
```

## Input / Output Contract

### Input (read from `GlobalState`)

| Field | Type | Source |
|---|---|---|
| `customer_id` | `str` | Ingestion layer / ticket metadata |

### Output (written to `GlobalState`)

| Field | Type | Description |
|---|---|---|
| `client_context` | `ClientContext` | Tenant context with inventory, dependencies, baselines, known_changes |
| `topology_nodes` | `List[TopologyNode]` | One node per inventory item (id, role, ref, metadata) |
| `topology_edges` | `List[TopologyEdge]` | One edge per dependency (source_id, target_id, relation); confidence=1.0 |
| `missing_info` | `List[str]` | Set when customer_id is absent or context not found |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `LLM_MODEL_CONTEXT` | `gpt-5-nano` | Configured but not currently used by this agent (no LLM calls) |

## Key Implementation Details

- Uses `async_session_factory` for database access; all queries are tenant-scoped by `customer_id`.
- Topology nodes inherit `id`, `role` (as `node_type`), `ref` (as `label`), and `metadata` from inventory items.
- Topology edges set `confidence=1.0` and `evidence_ref="inventory"` since they come from known inventory data.
- Edge direction is always `"uni"` (unidirectional) for dependency-sourced edges.
- Does not set `case_status`; the classifier sets it to `"triaged"` in the next step.

## See Also

- [architecture/data_layer.md](../architecture/data_layer.md)
- [agents/mapper.md](mapper.md)
- [agents/classifier.md](classifier.md)
