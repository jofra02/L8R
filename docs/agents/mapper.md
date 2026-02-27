# Mapper Agent

## Description
The Mapper Agent parses the ticket text to identify specific technical components (devices, IPs, URLs, services, users) involved in the issue. It matches against the customer's inventory when available and infers the vendor from context.

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
You are an expert IT Support / Incident Engineer. Analyze the ticket and identify technical components (devices, IPs, URLs, services, users). Match against inventory if possible. Infer the 'vendor' if explicitly mentioned or implied by the context.
```

**User:**
```text
Context: {inventory_summary}

Ticket: {text}

{format_instructions}
```

## Key Logic & Interactions
- **LLM Model:** Uses `LLM_MODEL_MAPPER` (e.g., `gpt-5-nano`) — fast, cheap NLP task.
- **Inventory Summary:** To avoid overflowing the context window, large inventories are summarized (e.g., "Customer has 50 assets").
- **Vendor Inference:** The prompt asks to infer vendors from context (e.g., "FortiGate" → "Fortinet"), which is critical for tool selection.
- **Component Roles:** Supports 30+ roles across networking, infrastructure, cloud, and application domains.
- **Output Parsing:** Uses `PydanticOutputParser` to generate strictly typed `Component` objects.
