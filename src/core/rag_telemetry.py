import time
import logging
import json
import functools
from typing import Any, Callable, Dict, Optional
from datetime import datetime

logger = logging.getLogger("rag_telemetry")

def rag_telemetry(operation_name: str):
    """
    Decorator to trace Vector Store operations.
    Logs structured JSON with latency, payload size, and status.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            success = True
            error_msg = None
            payload_size = 0
            
            # Estimate payload size from args (very rough)
            try:
                # 1st arg is self, skip it. 
                # Look for 'texts', 'metadatas', or specific model args
                for arg in args[1:]:
                   payload_size += len(str(arg))
                for v in kwargs.values():
                   payload_size += len(str(v))
            except:
                pass

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error_msg = str(e)
                raise e
            finally:
                duration_ms = (time.perf_counter() - start_time) * 1000
                
                log_data = {
                    "event": "rag_op",
                    "op": operation_name,
                    "latency_ms": round(duration_ms, 2),
                    "payload_bytes": payload_size,
                    "success": success,
                    "timestamp": datetime.now().isoformat()
                }
                
                if error_msg:
                    log_data["error"] = error_msg
                    logger.error(json.dumps(log_data))
                else:
                    # Use INFO for writes, DEBUG for reads to reduce noise? 
                    # For now, INFO is good for visibility.
                    logger.info(json.dumps(log_data))
                    
        return wrapper
    return decorator
