"""Tracing middleware for the gateway.

Times every MCP message (request + notification), logs method/source/duration
and publishes a Prometheus histogram when prometheus_client is installed.
"""

import logging
import time
from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext

logger = logging.getLogger("gateway.tracing")

try:
    from prometheus_client import Histogram

    REQUEST_LATENCY = Histogram(
        "mcp_gateway_request_latency_seconds",
        "Latency of MCP calls through the gateway",
        ["method"],
    )
except ImportError:
    REQUEST_LATENCY = None


class TracingMiddleware(Middleware):
    async def on_message(
        self,
        context: MiddlewareContext,
        call_next: Any,
    ):
        start = time.perf_counter()
        result = await call_next(context)
        duration = time.perf_counter() - start

        logger.info(
            "%s from %s in %.3f s",
            context.method,
            context.source,
            duration,
        )

        if REQUEST_LATENCY:
            REQUEST_LATENCY.labels(context.method).observe(duration)

        return result
