from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Dict, Any, List

class Settings(BaseSettings):
    """Global application settings."""
    
    # App
    APP_NAME: str = "SupportAI-Agent"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    
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
             "url": "http://generico.jdreconquista.com.ar:19568/sse"
         }
    }
    
    # --- LLM Profiles (Governance) ---
    
    # Main Profile (Reasoning: Planner, Hypothesis, Supervisor)
    LLM_MAIN_VENDOR: str = "openai" # openai, anthropic
    LLM_MAIN_MODEL: str = "gpt-5.2"
    LLM_MAIN_TEMP: float = 0.0
    LLM_MAIN_API_KEY: Optional[str] = None # Defaults to env var if None

    # Fast Profile (Speed: Classifier, Mapper, Normalizer)
    LLM_FAST_VENDOR: str = "openai"
    LLM_FAST_MODEL: str = "gpt-5-mini"
    LLM_FAST_TEMP: float = 0.0
    LLM_FAST_API_KEY: Optional[str] = None # Defaults to env var if None
    
    # Safety & Governance
    SAFETY_BLOCKED_KEYWORDS: List[str] = [
        "debug flow", "sniffer", "packet capture", "pcap", "tcpdump", "wireshark",
        "execute", "configure", "set ", "edit ", "delete", "rm ", "shutdown", "reboot"
    ]

    # Global API Keys
    OPENAI_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
