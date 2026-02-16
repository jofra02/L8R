from langchain_openai import ChatOpenAI
from src.config import settings
import logging

logger = logging.getLogger(__name__)

class LLMFactory:
    """Factory for getting LLM instances."""
    
    @staticmethod
    def get_main_llm(temperature: float = 0.0) -> ChatOpenAI:
        """Get the primary reasoning LLM (e.g., GPT-4o or equivalent)."""
        # In a real scenario, we might support multiple providers.
        # For now, default to OpenAI compatible env vars.
        return ChatOpenAI(
            model="gpt-4o",  # Or from settings
            temperature=temperature,
            api_key=settings.QDRANT_API_KEY # Reusing key or assume env var OPENAI_API_KEY is set
        )

    @staticmethod
    def get_fast_llm(temperature: float = 0.0) -> ChatOpenAI:
        """Get a faster/cheaper LLM for simple tasks."""
        return ChatOpenAI(
            model="gpt-4o-mini", 
            temperature=temperature
        )
