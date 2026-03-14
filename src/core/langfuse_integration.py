"""
Langfuse observability integration — single source of truth.

Provides:
- LangfuseManager: lazy singleton for client, traces, spans, callback handlers
- ContextVar helpers for async-safe trace/span propagation across the pipeline
"""

import logging
import random
import contextvars
from typing import Optional, Any, Dict

from src.config import settings

logger = logging.getLogger(__name__)

# --- Async-safe context propagation ---

_current_trace: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar(
    "_current_trace", default=None
)
_current_span: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar(
    "_current_span", default=None
)


def set_current_trace(trace: Any) -> None:
    _current_trace.set(trace)


def get_current_trace() -> Optional[Any]:
    return _current_trace.get()


def set_current_span(span: Any) -> None:
    _current_span.set(span)


def get_current_span() -> Optional[Any]:
    return _current_span.get()


class LangfuseManager:
    """Lazy singleton managing all Langfuse SDK interactions."""

    def __init__(self):
        self._client = None
        self._initialized = False

    def get_client(self):
        """Return Langfuse client instance, or None if disabled/unavailable."""
        if not settings.LANGFUSE_ENABLED:
            return None

        if self._initialized:
            return self._client

        self._initialized = True
        try:
            from langfuse import Langfuse

            self._client = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
                flush_at=settings.LANGFUSE_FLUSH_AT,
                flush_interval=settings.LANGFUSE_FLUSH_INTERVAL,
            )
            logger.info(f"Langfuse client initialized (host={settings.LANGFUSE_HOST})")
        except Exception as e:
            logger.warning(f"Langfuse initialization failed, observability disabled: {e}")
            self._client = None

        return self._client

    def create_trace(
        self,
        run_id: str,
        ticket_id: str,
        customer_id: str,
        thread_id: str,
    ) -> Optional[Any]:
        """Create a root trace for a pipeline execution. Returns None if disabled or sampled out."""
        client = self.get_client()
        if not client:
            return None

        # Sampling
        if settings.LANGFUSE_SAMPLE_RATE < 1.0 and random.random() > settings.LANGFUSE_SAMPLE_RATE:
            logger.debug(f"Langfuse trace sampled out for run_id={run_id}")
            return None

        try:
            trace = client.trace(
                id=run_id,
                session_id=thread_id,
                user_id=customer_id,
                metadata={"ticket_id": ticket_id},
                tags=[settings.APP_ENV],
            )
            logger.debug(f"Langfuse trace created: run_id={run_id}")
            return trace
        except Exception as e:
            logger.warning(f"Langfuse trace creation failed: {e}")
            return None

    def get_callback_handler_for_span(
        self, span: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """Return a LangChain CallbackHandler bound to the given span. None if unavailable."""
        if not span:
            return None

        try:
            from langfuse.callback import CallbackHandler

            trace = get_current_trace()
            if not trace:
                return None

            handler = CallbackHandler(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
                trace_id=trace.id,
                parent_observation_id=span.id,
                metadata=metadata or {},
            )
            return handler
        except Exception as e:
            logger.warning(f"Langfuse callback handler creation failed: {e}")
            return None

    def create_span(
        self,
        parent: Any,
        name: str,
        input: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Create a child span under a trace or parent span."""
        if not parent:
            return None

        try:
            span = parent.span(
                name=name,
                input=input,
                metadata=metadata or {},
            )
            return span
        except Exception as e:
            logger.warning(f"Langfuse span creation failed ({name}): {e}")
            return None

    def flush(self) -> None:
        """Graceful flush — call on shutdown."""
        if self._client:
            try:
                self._client.flush()
                logger.info("Langfuse client flushed.")
            except Exception as e:
                logger.warning(f"Langfuse flush failed: {e}")


# Module-level singleton
langfuse_manager = LangfuseManager()
