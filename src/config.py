from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Dict, Any, List

class Settings(BaseSettings):
    """Global application settings."""
    
    # App
    APP_NAME: str = "SupportAI-Agent"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    TEST_MODE_FAST: bool = False
    
    # Database (Postgres)
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASS: str = "postgres"
    DB_NAME: str = "support_agent_db"
    
    # Vector Store (Qdrant)
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    
    # MCP
    MCP_SERVER_TIMEOUT: int = 30
    MCP_SERVERS: Dict[str, Dict[str, Any]] = {
        # --- Examples ---
        # "filesystem": {
        #     "transport": "stdio",
        #     "command": "npx", 
        #     "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        # },
        # "remote-server": {
        #     "transport": "sse",
        #     "url": "http://localhost:8000/sse"
        # }
         "remote-server": {
             "transport": "sse",
             "url": "http://100.112.130.105:8000/sse"
         }
    }
    
    # --- LLM Profiles (Governance) ---
    
    # Per-Agent Models (Cost/Speed Optimization)
    LLM_MODEL_CLASSIFIER: str = "gpt-5-nano"
    LLM_MODEL_CONTEXT: str = "gpt-5-nano"
    LLM_MODEL_MAPPER: str = "gpt-5-nano"
    LLM_MODEL_SUPERVISOR: str = "gpt-5-mini" 
    LLM_MODEL_EVIDENCE_COLLECTOR: str = "gpt-4.1-mini"
    LLM_MODEL_ENRICHER: str = "gpt-5-mini"
    LLM_MODEL_HYPOTHESIS: str = "gpt-5.2"
    LLM_MODEL_INVESTIGATOR: str = "gpt-5.2"
    LLM_MODEL_PLANNER: str = "gpt-5.2"
    LLM_MODEL_RESPONSE: str = "gpt-5-mini"
    
    # Global Tuning
    LLM_REASONING_EFFORT: str = "low" # Can be injected into reasoning models to speed up tasks
    LLM_TEMPERATURE_DEFAULT: float = 0.0
    
    # Safety & Governance
    SAFETY_BLOCKED_KEYWORDS: List[str] = [
        "debug flow", "sniffer", "packet capture", "pcap", "tcpdump", "wireshark",
        "execute", "configure", "set ", "edit ", "delete", "rm ", "shutdown", "reboot",
        "drop database", "truncate", "format", "destroy", "purge", "kill ",
        "deploy", "push", "publish", "migrate", "alter ", "grant ", "revoke "
    ]

    # Global API Keys
    OPENAI_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
