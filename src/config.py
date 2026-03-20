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
    QDRANT_TIMEOUT: int = 60

    # Embedding
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    EMBEDDING_BATCH_SIZE: int = 64

    # Qdrant Search Tuning
    QDRANT_HNSW_EF: int = 128
    QDRANT_INDEXED_ONLY: bool = False
    QDRANT_ON_DISK_PAYLOAD: bool = True

    # Per-collection score thresholds
    QDRANT_SCORE_TOOL_CATALOG: float = 0.15
    QDRANT_SCORE_ADAPTIVE_FIXES: float = 0.75
    QDRANT_SCORE_EVIDENCE: float = 0.7
    QDRANT_SCORE_KNOWLEDGE_BASE: float = 0.5
    QDRANT_SCORE_RESOLVED_TICKETS: float = 0.0
    QDRANT_SCORE_TOOL_KNOWLEDGE: float = 0.0

    # Hybrid Search
    QDRANT_HYBRID_ENABLED: bool = False
    QDRANT_HYBRID_COLLECTIONS: List[str] = ["tool_catalog", "adaptive_fixes", "knowledge_base"]
    
    # MCP Server → Vendor mapping (config-driven, primary vendor extraction)
    MCP_SERVER_VENDOR_MAP: Dict[str, str] = {}

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
    LLM_MODEL_CLASSIFIER: str = "gpt-5.4-nano"
    LLM_MODEL_CONTEXT: str = "gpt-5.4-nano"
    LLM_MODEL_MAPPER: str = "gpt-5.4-nano"
    LLM_MODEL_SUPERVISOR: str = "gpt-5.4-mini" 
    LLM_MODEL_EVIDENCE_COLLECTOR: str = "gpt-5.4-mini"
    LLM_MODEL_ENRICHER: str = "gpt-5.4-mini"
    LLM_MODEL_HYPOTHESIS: str = "gpt-5.4"
    LLM_MODEL_INVESTIGATOR: str = "gpt-5.4"
    LLM_MODEL_PLANNER: str = "gpt-5.4"
    LLM_MODEL_RESPONSE: str = "gpt-5.4-nano"
    LLM_MODEL_ADAPTIVE_FIX: str = "gpt-5-nano"
    
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

    # Langfuse Observability
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: Optional[str] = None
    LANGFUSE_SECRET_KEY: Optional[str] = None
    LANGFUSE_HOST: str = "http://localhost:3000"
    LANGFUSE_SAMPLE_RATE: float = 1.0
    LANGFUSE_FLUSH_AT: int = 15
    LANGFUSE_FLUSH_INTERVAL: int = 5

    # Global API Keys
    OPENAI_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
