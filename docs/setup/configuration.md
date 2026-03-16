# Configuration Reference

> Complete environment variable reference extracted from `src/config.py`.

## Overview

All configuration is managed through environment variables, loaded via Pydantic Settings from a `.env` file in the project root. The `Settings` class in `src/config.py` defines all available options with their types and defaults.

## Environment Variables

### Application

| Variable | Type | Default | Description |
|---|---|---|---|
| `APP_NAME` | `str` | `SupportAI-Agent` | Application name (used in API title) |
| `APP_ENV` | `str` | `development` | Environment identifier |
| `LOG_LEVEL` | `str` | `INFO` | Python logging level |
| `TEST_MODE_FAST` | `bool` | `False` | Reduces iterations (8 vs 15) and retries (1 vs 2) for testing |

### PostgreSQL

| Variable | Type | Default | Description |
|---|---|---|---|
| `DB_HOST` | `str` | `localhost` | Database host |
| `DB_PORT` | `int` | `5432` | Database port |
| `DB_USER` | `str` | `postgres` | Database user |
| `DB_PASS` | `str` | `postgres` | Database password |
| `DB_NAME` | `str` | `support_agent_db` | Database name |

### Qdrant (Vector Store)

| Variable | Type | Default | Description |
|---|---|---|---|
| `QDRANT_URL` | `str` | `http://localhost:6333` | Qdrant server URL |
| `QDRANT_API_KEY` | `str?` | `None` | Qdrant API key (optional, for cloud) |

### MCP (Model Context Protocol)

| Variable | Type | Default | Description |
|---|---|---|---|
| `MCP_SERVER_TIMEOUT` | `int` | `30` | Timeout in seconds for MCP tool calls |
| `MCP_SERVERS` | `dict` | See below | MCP server connection definitions |

MCP servers are configured as a JSON dict. Each entry defines a transport (`stdio` or `sse`) and connection params:

```json
{
  "remote-server": {
    "transport": "sse",
    "url": "http://localhost:8000/sse"
  }
}
```

### LLM Profiles (Per-Agent Model Governance)

| Variable | Type | Default | Description |
|---|---|---|---|
| `LLM_MODEL_CLASSIFIER` | `str` | `gpt-5-nano` | Model for domain classification |
| `LLM_MODEL_CONTEXT` | `str` | `gpt-5-nano` | Model for context agent |
| `LLM_MODEL_MAPPER` | `str` | `gpt-5-nano` | Model for component mapping |
| `LLM_MODEL_SUPERVISOR` | `str` | `gpt-5-mini` | Model for supervisor routing (unused — routing is deterministic) |
| `LLM_MODEL_EVIDENCE_COLLECTOR` | `str` | `gpt-4.1-mini` | Model for intent generation + tool argument binding |
| `LLM_MODEL_ENRICHER` | `str` | `gpt-5-mini` | Model for fact/topology extraction |
| `LLM_MODEL_HYPOTHESIS` | `str` | `gpt-5.2` | Model for hypothesis generation + path analysis |
| `LLM_MODEL_INVESTIGATOR` | `str` | `gpt-5.2` | Model for investigation + adaptive executor diagnosis |
| `LLM_MODEL_PLANNER` | `str` | `gpt-5.2` | Model for resolution plan generation |
| `LLM_MODEL_RESPONSE` | `str` | `gpt-5-mini` | Model for final report generation |
| `LLM_REASONING_EFFORT` | `str` | `low` | Reasoning effort level for compatible models |
| `LLM_TEMPERATURE_DEFAULT` | `float` | `0.0` | Default temperature for all LLM calls |

### Safety and Governance

| Variable | Type | Default | Description |
|---|---|---|---|
| `SAFETY_BLOCKED_KEYWORDS` | `list[str]` | See below | Keywords that block tool execution |

Default blocked keywords include: `debug flow`, `sniffer`, `packet capture`, `pcap`, `tcpdump`, `wireshark`, `execute`, `configure`, `set`, `edit`, `delete`, `rm`, `shutdown`, `reboot`, `drop database`, `truncate`, `format`, `destroy`, `purge`, `kill`, `deploy`, `push`, `publish`, `migrate`, `alter`, `grant`, `revoke`.

### Langfuse Observability

| Variable | Type | Default | Description |
|---|---|---|---|
| `LANGFUSE_ENABLED` | `bool` | `False` | Enable/disable Langfuse integration |
| `LANGFUSE_PUBLIC_KEY` | `str?` | `None` | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | `str?` | `None` | Langfuse secret key |
| `LANGFUSE_HOST` | `str` | `http://localhost:3000` | Langfuse server URL |
| `LANGFUSE_SAMPLE_RATE` | `float` | `1.0` | Trace sampling rate (0.0-1.0) |
| `LANGFUSE_FLUSH_AT` | `int` | `15` | Batch size before flushing to Langfuse |
| `LANGFUSE_FLUSH_INTERVAL` | `int` | `5` | Flush interval in seconds |

### API Keys

| Variable | Type | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | `str?` | `None` | OpenAI API key (required for LLM calls) |

## Configuration Loading

Settings are loaded in this order (later overrides earlier):
1. Default values in `Settings` class
2. `.env` file in project root (`env_file_encoding="utf-8"`)
3. Environment variables

The `extra="ignore"` setting means unknown env vars are silently ignored.

## See Also

- [Quickstart](quickstart.md) - Minimal setup steps
- [Deployment Guide](deployment.md) - Production configuration
- [Safety and Governance](../architecture/safety_and_governance.md) - Tool governance details
