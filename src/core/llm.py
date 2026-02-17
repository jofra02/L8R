from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from src.config import settings
import logging
import os

logger = logging.getLogger(__name__)

class LLMFactory:
    """
    Factory for getting LLM instances based on configured profiles.
    """
    
    @staticmethod
    def get_main_llm() -> BaseChatModel:
        """
        Get the primary reasoning LLM (configured as LLM_MAIN_*).
        Used for: Supervisor, Planner, Hypothesis, Response.
        """
        # Determine API Key: Specific Override -> Global Setting -> Env Var
        api_key = settings.LLM_MAIN_API_KEY or settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
        
        return ChatOpenAI(
            model=settings.LLM_MAIN_MODEL,
            temperature=settings.LLM_MAIN_TEMP,
            api_key=api_key
        )

    @staticmethod
    def get_fast_llm() -> BaseChatModel:
        """
        Get the fast/efficient LLM (configured as LLM_FAST_*).
        Used for: Classifier, Mapper, Normalizer, Context.
        """
        api_key = settings.LLM_FAST_API_KEY or settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
        
        return ChatOpenAI(
            model=settings.LLM_FAST_MODEL,
            temperature=settings.LLM_FAST_TEMP,
            api_key=api_key
        )
