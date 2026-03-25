"""
Langfuse observability integration — single source of truth.

Provides:
- LangfuseManager: lazy singleton for client, traces, spans, callback handlers
- ContextVar helpers for async-safe trace/span propagation across the pipeline

SDK target: langfuse >= 2.44.0 / 4.x (supports both v2 and v4 APIs).
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


class TraceRef:
    """Lightweight reference to a Langfuse trace (trace_id + client).

    The OTel-based Langfuse SDK has no explicit 'trace' object.
    A trace is defined by its trace_id; spans reference it via trace_context.
    This object carries the trace_id so callers can create top-level spans.
    """

    def __init__(self, trace_id: str, client: Any):
        self.trace_id = trace_id
        self.id = trace_id
        self._client = client


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
    ) -> Optional["TraceRef"]:
        """Create a trace reference for a pipeline execution. Returns None if disabled or sampled out."""
        client = self.get_client()
        if not client:
            return None

        # Sampling
        if settings.LANGFUSE_SAMPLE_RATE < 1.0 and random.random() > settings.LANGFUSE_SAMPLE_RATE:
            logger.debug(f"Langfuse trace sampled out for run_id={run_id}")
            return None

        # OTel requires trace_id as 32-char lowercase hex (no dashes)
        trace_id = run_id.replace("-", "")
        logger.debug(f"Langfuse trace created: run_id={run_id}, trace_id={trace_id}")
        return TraceRef(trace_id=trace_id, client=client)

    def get_callback_handler_for_span(
        self, span_or_trace: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """Return a LangChain CallbackHandler nested under the given trace/span.

        Uses langfuse.callback.CallbackHandler with stateful_client to nest
        all LLM generations and tool calls under the parent trace or span.
        """
        if not span_or_trace:
            return None

        client = self.get_client()
        if not client:
            return None

        try:
            # langfuse v4: langfuse.langchain
            # langfuse v2: langfuse.callback
            try:
                from langfuse.langchain import CallbackHandler
            except ImportError:
                from langfuse.callback import CallbackHandler

            if isinstance(span_or_trace, TraceRef):
                # v4 uses trace_context; v2 uses stateful_client
                try:
                    handler = CallbackHandler(
                        trace_context={"trace_id": span_or_trace.trace_id},
                    )
                except TypeError:
                    trace_client = client.trace(id=span_or_trace.trace_id)
                    handler = CallbackHandler(
                        stateful_client=trace_client,
                        metadata=metadata,
                    )
            else:
                handler = CallbackHandler()
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
        """Create a child span under a TraceRef or parent span."""
        if not parent:
            return None

        try:
            if isinstance(parent, TraceRef):
                # Top-level span under a trace — use the client directly
                return parent._client.start_observation(
                    name=name,
                    input=input,
                    metadata=metadata or {},
                    trace_context={"trace_id": parent.trace_id},
                )
            else:
                # Child span under an existing observation
                return parent.start_observation(
                    name=name,
                    input=input,
                    metadata=metadata or {},
                )
        except Exception as e:
            logger.warning(f"Langfuse span creation failed ({name}): {e}")
            return None

    @staticmethod
    def end_span(
        span: Any,
        output: Optional[Any] = None,
        level: Optional[str] = None,
        status_message: Optional[str] = None,
    ) -> None:
        """End a span, optionally setting output/level/status_message via update() first.

        The OTel-based SDK's span.end() only accepts end_time.
        Use span.update() to set output, level, and status_message before ending.
        """
        if not span:
            return
        try:
            if output is not None or level is not None or status_message is not None:
                kwargs: Dict[str, Any] = {}
                if output is not None:
                    kwargs["output"] = output
                if level is not None:
                    kwargs["level"] = level
                if status_message is not None:
                    kwargs["status_message"] = status_message
                span.update(**kwargs)
            span.end()
        except Exception:
            pass

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
