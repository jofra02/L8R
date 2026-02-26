# Mapper Agent

## Description
The Mapper Agent (also referred to as Scoper) parses the ticket text to identify specific technical components (drivers, devices, IPs, URLs) involved in the issue. It attempts to link these components to the customer's inventory if available.

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
You are an expert IT Support AI. Analyze the ticket and identify technical components (devices, IPs, URLs, services, users). Match against inventory if possible. Infer the 'vendor' (e.g. Fortinet, Cisco, AWS, Microsoft) if explicitly mentioned or implied by the context.
```

**User:**
```text
Context: {inventory_summary}

Ticket: {text}

{format_instructions}
```

## Key Logic & Interactions
-   **LLM Model:** Uses `LLM_MODEL_MAPPER` (e.g., `gpt-5-nano`), since entity extraction is a fast, cheap NLP task.
-   **Inventory Summary:** To avoid overflowing the context window, the agent does not pass the full inventory list if it's large. Instead, it passes a summary (e.g., "Customer has 50 assets").
-   **Vendor Inference:** The prompt explicitly asks to infer vendors (e.g., "FortiGate" -> "Fortinet"), which is crucial for the Evidence Collector to select the right tools later.
-   **Output Parsing:** Uses `PydanticOutputParser` to generate strictly typed `Component` objects.
