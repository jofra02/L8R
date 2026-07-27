> Historical design spec — applies to the legacy multi-agent pipeline only. Engineer mode uses a single model set via `LLM_MODEL_ENGINEER`; the per-agent profiles below survive only behind `PIPELINE_MODE=pipeline`. Current reference: [Configuration](../../setup/configuration.md).

# Model Governance & Configuration Plan

To address the need for granular LLM control (Vendor, Model, Token) per agent, we will upgrade the `LLMFactory` and `Settings`.

## 1. Strategy: Model Profiles
Instead of hardcoding "gpt-4o", we will define abstract **Model Profiles** in `src/config.py`.
This allows us to switch vendors or models globally or per-tier without touching agent code.

### Proposed Profiles
1.  **Main (Reasoning)**: For complex tasks (Planner, Hypothesis, Supervisor).
    *   *Default*: `gpt-4o`
2.  **Fast (Parsing/Ingest)**: For high-volume, low-latency tasks (Classifier, Mapper, Normalizer).
    *   *Default*: `gpt-4o-mini`

## 2. Configuration (`src/config.py`)

We will add explicit settings for these profiles.

```python
class Settings(BaseSettings):
    # ... existing DB settings ...

    # --- LLM Main (Reasoning) ---
    LLM_MAIN_VENDOR: str = "openai" # openai, anthropic, azure
    LLM_MAIN_MODEL: str = "gpt-4o"
    LLM_MAIN_TEMP: float = 0.0
    LLM_MAIN_API_KEY: Optional[str] = None # Defaults to OPENAI_API_KEY env var if blank

    # --- LLM Fast (Speed) ---
    LLM_FAST_VENDOR: str = "openai"
    LLM_FAST_MODEL: str = "gpt-4o-mini"
    LLM_FAST_TEMP: float = 0.0
    LLM_FAST_API_KEY: Optional[str] = None
```

## 3. Factory Implementation (`src/core/llm.py`)

The `LLMFactory` will be updated to read these settings and instantiate the correct `LangChain` chat object.

```python
class LLMFactory:
    @staticmethod
    def get_main_llm() -> BaseChatModel:
        # Reads settings.LLM_MAIN_*
        # Returns ChatOpenAI configured with specific model/key
        pass

    @staticmethod
    def get_fast_llm() -> BaseChatModel:
        # Reads settings.LLM_FAST_*
        pass
```

## 4. Agent Mapping

Each agent will request a specific profile during initialization in `src/agent_graph.py` or within the node definition.

| Agent | Profile | Rationale |
| :--- | :--- | :--- |
| **Supervisor** | Main | Needs robust routing logic. |
| **Context** | Fast | Simple retrieval/summarization. |
| **Classifier** | Fast | Rapid categorization. |
| **Mapper** | Fast | Entity extraction. |
| **Evidence Collector** | Main | Complex tool selection. |
| **Enricher** | Fast | Data formatting. |
| **Hypothesis** | Main | deep reasoning/abduction. |
| **Planner** | Main | Logical step generation. |
| **Response** | Main | Polished final output. |

## 5. Environment Variables (`.env`)

You will manage the "Vendor - Model - Token" info here:

```ini
# Defaults (OpenAI)
OPENAI_API_KEY=sk-...

# Overrides (if needed)
LLM_MAIN_MODEL=gpt-4-turbo
LLM_FAST_MODEL=gpt-3.5-turbo
```
