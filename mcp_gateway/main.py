"""MCP Gateway entry point.

All runtime configuration comes from environment variables (no CLI flags):

    SERVER_TRANSPORT  sse (default) | stdio
    SERVER_HOST       default 0.0.0.0
    SERVER_PORT       default 8000
    UVICORN_RELOAD    default false
    LOG_LEVEL         default info
"""

import os

from gateway.app import gateway

if __name__ == "__main__":
    import uvicorn

    transport = os.getenv("SERVER_TRANSPORT", "sse")
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))
    reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "info").lower()

    if transport == "stdio":
        gateway.run(transport="stdio")
    else:
        print(f"Starting MCP Gateway on {host}:{port} (SSE at /sse/)")
        uvicorn.run("gateway.app:app", host=host, port=port, reload=reload, log_level=log_level)
