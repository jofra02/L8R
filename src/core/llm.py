from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from src.config import settings
import logging
import os

logger = logging.getLogger(__name__)

from typing import Optional

class LLMFactory:
    """
    Factory for getting LLM instances based on configured profiles.
    """

    @staticmethod
    def get_model_for_agent(agent_name: str, temperature: Optional[float] = None) -> BaseChatModel:
        """
        Get the specific LLM configured for a given agent.
        Injects reasoning_effort to optimize speed for reasoning models.

        Note: Langfuse observability callbacks are NOT attached here.
        They are injected at the invocation site (e.g., react_agent.ainvoke config)
        to ensure propagation through the full execution chain.
        """
        api_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")

        # Retrieve the specific model for the requested agent, fallback to gpt-5-mini
        config_key = f"LLM_MODEL_{agent_name.upper()}"
        model_name = getattr(settings, config_key, "gpt-5-mini")

        kwargs = {
            "model": model_name,
            "temperature": temperature if temperature is not None else settings.LLM_TEMPERATURE_DEFAULT,
            "api_key": api_key
        }

        # Apply reasoning_effort if configured AND not the engineer agent
        reasoning = getattr(settings, "LLM_REASONING_EFFORT", None)
        if reasoning and agent_name != "engineer" and any(token in model_name for token in ["o1", "o3", "gpt-5"]):
            kwargs["reasoning_effort"] = reasoning

        # Engineer reasoning effort is configured separately: some models reject
        # function tools on chat completions unless reasoning_effort is explicit
        # (e.g. "none").
        if agent_name == "engineer" and settings.LLM_REASONING_EFFORT_ENGINEER:
            kwargs["reasoning_effort"] = settings.LLM_REASONING_EFFORT_ENGINEER

        return ChatOpenAI(**kwargs)
