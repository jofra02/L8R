# Context Agent

## Description
The Context Agent is the first specialist node to run. It hydrates the global state with client-specific information (inventory, baselines, known changes) and **seeds the topology graph** from known infrastructure dependencies.

## Role in Graph
- **Node Name:** `context_agent`
- **Upstream:** `supervisor` (typically the first step)
- **Downstream:** `supervisor` (returns to router)

## Inputs
- `state["customer_id"]`: The ID of the customer to look up.

## Outputs
- `state["client_context"]`: A `ClientContext` object containing inventory, dependencies, baselines, known changes.
- `state["topology_nodes"]`: Seeded from `client_context.inventory` — each inventory component becomes a topology node.
- `state["topology_edges"]`: Seeded from `client_context.dependencies` — known relationships between components (confidence=1.0).
- `state["missing_info"]`: Populated if context cannot be found.

## Key Logic
1. Connects to the `ContextStore` (backed by PostgreSQL/ORM via `ClientContextORM`).
2. Queries for the latest active context associated with `customer_id`.
3. If found, seeds the topology graph:
   - **Inventory → Nodes**: Each `Component` becomes a `TopologyNode` with `node_type=role`, `label=ref`.
   - **Dependencies → Edges**: Each `InventoryDependency` becomes a `TopologyEdge` with `confidence=1.0` and `evidence_ref="inventory"`.
4. If **not found**, returns a default/empty context with a warning flag.

## Interactions
This agent does not use an LLM. It is a deterministic data retrieval node. Its output is critical for:
- **Mapper**: Links ticket entities to inventory assets.
- **Hypothesis**: Baselines and known changes provide context for root cause analysis.
- **Enricher/Hypothesis**: The seeded topology graph provides initial entity relationships.
