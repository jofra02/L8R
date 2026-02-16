from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

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
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
