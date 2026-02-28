# Mapper Agent

## Description
The Mapper Agent parses the ticket text to identify specific technical components involved in the issue. It matches against the customer's inventory when available and infers the vendor from context. A deterministic reconciliation step corrects LLM-generated IDs against the real inventory.

## Role in Graph
- **Node Name:** `mapper_agent`
- **Upstream:** `supervisor`
- **Downstream:** `supervisor`

## Inputs
- `state["ticket"]`: Ticket text.
- `state["client_context"]`: Inventory data (used for matching).

## Outputs
- `state["components"]`: A list of `Component` objects representing the entities gathered from the ticket.

## Prompts

### Component Scoping
**System:**
```text
You are an expert IT Support / Incident Engineer. Analyze the ticket and identify technical components (devices, IPs, URLs, services, users, applications, databases, clusters, containers, APIs, storage, endpoints). When a component matches an inventory item, use that item's exact `id` value as the component `id`. Only generate a new id for components not present in the inventory. Infer the 'vendor' if explicitly mentioned or implied by the context.
```

**User:**
```text
Inventory: {inventory_summary}

Ticket: {text}

{format_instructions}
```

## Post-Processing: Inventory Reconciliation

After the LLM generates components, a deterministic `_reconcile_with_inventory()` function corrects IDs against the real inventory using 4 strategies (in order):

1. **Exact ID match** — normalize casing against canonical inventory ID.
2. **Prefix strip** — remove common LLM-generated prefixes (`comp_`, `component_`, `asset_`, `device_`, `host_`) and re-check.
3. **Substring match** — check if the generated ID contains (or is contained by) an inventory ID.
4. **Ref-based match** — check if the LLM used the human-readable `ref` name as the `id`.

If no match is found, the component is kept as-is (unknown asset not in inventory).

## Key Logic & Interactions
- **LLM Model:** Uses `LLM_MODEL_MAPPER` (e.g., `gpt-5-nano`) — fast, cheap NLP task.
- **Inventory Summary:** To avoid overflowing the context window, large inventories (>50 items) are summarized.
- **Vendor Inference:** The prompt asks to infer vendors from context (e.g., "FortiGate" -> "Fortinet"), which is critical for tool selection.
- **Domain-Agnostic:** Supports components across all IT domains — networking, infrastructure, cloud, application, database, storage, etc.
- **Output Parsing:** Uses `PydanticOutputParser` to generate strictly typed `Component` objects.
