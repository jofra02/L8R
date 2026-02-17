# Context Agent

## Description
The Context Agent is the first specialist node to run. Its sole responsibility is to hydrate the global state with client-specific information (inventory, configuration baselines, known changes) based on the `customer_id`.

## Role in Graph
- **Node Name:** `context_agent`
- **Upstream:** `supervisor` (typically the first step)
- **Downstream:** `supervisor` (returns to router to decide next step)

## Inputs
- `state["customer_id"]`: The ID of the customer to look up.

## Outputs
- `state["client_context"]`: A `ClientContext` object containing inventory and relevant metadata.
- `state["missing_info"]`: Populated if context cannot be found.

## Key Logic
1.  Connects to the `ContextStore` (backed by PostgreSQL/ORM).
2.  Queries for the active context associated with `customer_id`.
3.  If found, returns the context object.
4.  If **not found**, it logs a warning and returns a default/empty context to allow the process to continue (graceful degradation), while flagging the missing info.

## Interactions
This agent does not use an LLM. It is a deterministic data retrieval node. Its output is critical for the `Mapper` agent to link ticket entities to actual inventory assets.
