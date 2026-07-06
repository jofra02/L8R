from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
import os
import re
import yaml
import logging

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MCP_SERVERS_PATH = _PROJECT_ROOT / "data" / "mcp" / "servers.yaml"

_ENV_VAR_PATTERN = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")


def _expand_env_vars(value: Any) -> Any:
    """Expand ${VAR} / ${VAR:-default} placeholders in strings, recursively.

    Lets servers.yaml point at different hosts per environment (e.g.
    MCP_GATEWAY_URL is http://mcp-gateway:8000/sse inside compose but
    defaults to localhost:8001 for host-run dev).
    """
    if isinstance(value, str):
        return _ENV_VAR_PATTERN.sub(
            lambda m: os.getenv(m.group("name"), m.group("default") or ""), value
        )
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


def _load_mcp_config() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """Load MCP server definitions from data/mcp/servers.yaml.

    Returns (servers_dict, vendor_map) where vendor_map is extracted
    from per-server 'vendor' fields.  Falls back to empty dicts if
    the file is missing or malformed.
    """
    servers: Dict[str, Dict[str, Any]] = {}
    vendor_map: Dict[str, str] = {}

    if not _MCP_SERVERS_PATH.exists():
        return servers, vendor_map

    try:
        raw = yaml.safe_load(_MCP_SERVERS_PATH.read_text(encoding="utf-8")) or {}
        raw = _expand_env_vars(raw)
        servers = raw.get("servers", {})
        if not isinstance(servers, dict):
            logger.warning("MCP servers.yaml: 'servers' key is not a dict, ignoring")
            return {}, {}

        # Extract vendor fields into a separate map and remove from server config
        for name, cfg in servers.items():
            vendor = cfg.pop("vendor", None)
            if vendor:
                vendor_map[name] = vendor

    except Exception as e:
        logger.warning(f"Failed to load {_MCP_SERVERS_PATH}: {e}")

    return servers, vendor_map


_mcp_servers, _mcp_vendor_map = _load_mcp_config()

class Settings(BaseSettings):
    """Global application settings."""
    
    # App
    APP_NAME: str = "SupportAI-Agent"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    TEST_MODE_FAST: bool = False

    # Pipeline Mode
    PIPELINE_MODE: str = "engineer"  # "pipeline" (multi-agent) | "engineer" (single-agent)

    # Engineer Agent Config
    LLM_MODEL_ENGINEER: str = "gpt-5.4"
    ENGINEER_MAX_TOOL_CALLS: int = 30
    ENGINEER_MAX_ITERATIONS: int = 50
    ENGINEER_TIMEOUT_SECONDS: int = 600
    
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
    
    # MCP Server → Vendor mapping (extracted from data/mcp/servers.yaml vendor fields)
    MCP_SERVER_VENDOR_MAP: Dict[str, str] = _mcp_vendor_map

    # MCP — loaded from data/mcp/servers.yaml (env var override still works)
    MCP_SERVER_TIMEOUT: int = 30
    MCP_SERVERS: Dict[str, Dict[str, Any]] = _mcp_servers
    
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
    LLM_REASONING_EFFORT: Optional[str] = None  # "low", "medium", "high", or None to skip
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

    # JWT
    JWT_SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Password Policy
    PASSWORD_MIN_LENGTH: int = 12
    PASSWORD_REQUIRE_UPPERCASE: bool = True
    PASSWORD_REQUIRE_SYMBOL: bool = True

    # Tool Category Search
    TOOL_CATEGORY_TIER1_MIN: int = 3
    TOOL_CATEGORY_TIER2_MIN: int = 3

    # Bootstrap
    BOOTSTRAP_ADMIN_EMAIL: str = "admin@localhost"

    # Global API Keys
    OPENAI_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
