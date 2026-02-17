# Classifier Agent

## Description
The Classifier Agent analyzes the raw ticket text to determine the technical domain (e.g., Network, Auth, Database) and assess the severity. This classification helps downstream agents (like Mapper and Evidence Collector) focus their efforts.

## Role in Graph
- **Node Name:** `classifier_agent`
- **Upstream:** `supervisor`
- **Downstream:** `supervisor`

## Inputs
- `state["ticket"]`: The ticket object containing the issue description.

## Outputs
- `state["classification"]`: A `Classification` object containing:
    -   `domains`: List of relevant technical domains.
    -   `confidence`: A score (0-1).
    -   `rationale`: Explanation for the classification.

## Prompts

### Ticket Classification
**System:**
```text
You are an expert IT Support AI. Classify the following ticket into technical domains (e.g., 'network', 'auth', 'database', 'hardware'). Provide a confidence score (0-1).
```

**User:**
```text
Ticket Text: {text}

{format_instructions}
```

## Key Logic & Interactions
-   Uses a "Fast LLM" (cheaper/faster model) as this is a relatively simple NLU task.
-   Uses `PydanticOutputParser` to ensure structured JSON output.
-   Includes a fallback mechanism: if the LLM fails or produces invalid JSON, it returns a default "unknown" classification to prevent the graph from crashing.
