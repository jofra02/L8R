# MCP Integration Guide

This guide explains how to connect the Support AI Agent Framework to **Model Context Protocol (MCP)** tools and servers.

## 🧩 Architecture

The framework uses a centralized **Capability Registry** to manage tools.

*   **Registry** (`src/core/registry.py`): The catalog of available tools.
*   **Client** (`src/mcp/client.py`): The executor that handles safety checks (Read-Only, Timeouts) and invokes the tool.
*   **Interfaces** (`src/core/interfaces.py`): Defins the `MCPToolInterface` contract.

## 🛠️ Option 1: Adding Internal Tools (Python)

The easiest way to add capabilities is by creating "Internal Tools" directly in Python.

### Step 1: Define Arguments
Create a Pydantic model for your tool's arguments.

```python
from pydantic import BaseModel, Field

class MyToolArgs(BaseModel):
    username: str = Field(description="Target username")
```

### Step 2: Implement Interface
Inherit from `MCPToolInterface` and implement `run()`.

```python
from src.core.interfaces import MCPToolInterface

class CheckUserTool(MCPToolInterface):
    name = "check_user"
    description = "Checks if a user exists in the system."
    args_schema = MyToolArgs

    async def run(self, username: str) -> str:
        # Your logic here (API call, DB query, etc.)
        return f"User {username} exists."
```

### Step 3: Register Tool
Add it to a Capability Pack (`src/capabilities/my_pack.py`) or register directly in `src.core.registry`.

```python
# In src/core/registry.py or pack loader
CapabilityRegistry._tools["check_user"] = CheckUserTool()
```

---

## 🔌 Option 2: Connecting External MCP Servers

The framework has built-in support for external MCP servers via the `mcp` Python SDK (Stdio).

### Step 1: Configuration

Define your servers in `src/config.py` via `MCP_SERVERS`. The `transport` key defaults to `"stdio"` but can be set to `"sse"`.

```python
# src/config.py
MCP_SERVERS = {
    # Option A: Stdio (Local Process)
    "filesystem": {
        "transport": "stdio",
        "command": "npx", 
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env": {"PATH": "/usr/bin"} # Optional
    },
    
    # Option B: SSE (Remote Server)
    "remote-tools": {
        "transport": "sse",
        "url": "http://localhost:8000/sse"
    }
}
```

### Step 2: Automatic Loading

On application startup, `CapabilityRegistry.load_external_tools()` is called. It will:
1.  Connect to each configured server (via Stdio).
2.  List available tools.
3.  Register them as internal `ExternalToolWrapper` proxies.

Agents can now see and use these tools transparently!
