import time
import logging
import json
import functools
from typing import Any, Callable
from datetime import datetime

logger = logging.getLogger("rag_telemetry")

_READ_PREFIXES = ("get_", "search_", "find_", "query_")
_WRITE_OPS = ("add_texts", "save_", "index_", "upsert", "delete")


def _extract_direction(operation_name: str) -> str:
    if any(operation_name.startswith(p) for p in _READ_PREFIXES):
        return "read"
    if any(operation_name.startswith(p) for p in _WRITE_OPS):
        return "write"
    return "write"


def _extract_score_range(result: Any) -> list | None:
    """Extract [min, max] scores from ScoredPoint results."""
    if not isinstance(result, list) or not result:
        return None
    scores = []
    for pt in result:
        score = getattr(pt, "score", None)
        if score is not None:
            scores.append(score)
    if scores:
        return [round(min(scores), 4), round(max(scores), 4)]
    return None


def _extract_result_count(result: Any) -> int | None:
    """Count results for search operations."""
    if isinstance(result, list):
        return len(result)
    return None


def rag_telemetry(operation_name: str):
    """
    Decorator to trace Vector Store operations.
    Logs structured JSON with latency, payload size, collection, tenant, and result stats.
    """
    direction = _extract_direction(operation_name)

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            success = True
            error_msg = None
            payload_size = 0

            # Extract collection_name from first positional arg after self
            collection = None
            if len(args) > 1 and isinstance(args[1], str):
                collection = args[1]

            # Extract customer_id from kwargs or positional args
            customer_id = kwargs.get("customer_id")
            if customer_id is None:
                # Scan positional args for customer_id (typically 3rd arg in search, varies elsewhere)
                # Best-effort: check kwargs first, fallback to None
                pass

            # Estimate payload size from args
            try:
                for arg in args[1:]:
                   payload_size += len(str(arg))
                for v in kwargs.values():
                   payload_size += len(str(v))
            except Exception:
                pass

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error_msg = str(e)
                raise
            finally:
                duration_ms = (time.perf_counter() - start_time) * 1000

                log_data = {
                    "event": "rag_op",
                    "op": operation_name,
                    "direction": direction,
                    "latency_ms": round(duration_ms, 2),
                    "payload_bytes": payload_size,
                    "success": success,
                    "timestamp": datetime.now().isoformat(),
                }

                if collection:
                    log_data["collection"] = collection
                if customer_id:
                    log_data["customer_id"] = customer_id

                # Post-call enrichment (only on success)
                if success and direction == "read":
                    try:
                        count = _extract_result_count(result)
                        if count is not None:
                            log_data["result_count"] = count
                        score_range = _extract_score_range(result)
                        if score_range is not None:
                            log_data["score_range"] = score_range
                    except Exception:
                        pass

                if error_msg:
                    log_data["error"] = error_msg
                    logger.error(json.dumps(log_data))
                else:
                    logger.info(json.dumps(log_data))

        return wrapper
    return decorator
