import asyncio
import logging
from typing import Dict, Any, List, Optional
from contextlib import AsyncExitStack

# MCP SDK Imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client # Assumption based on library structure
from mcp.types import CallToolResult, Tool

from src.config import settings
from src.core.interfaces import MCPToolInterface
from pydantic import BaseModel, create_model

logger = logging.getLogger(__name__)

class ExternalToolWrapper(MCPToolInterface):
    """
    Wraps an external MCP tool result into our internal interface.

    ``input_schema`` is the raw MCP inputSchema (JSON Schema) exactly as the
    server advertises it — types, formats, enums, and per-parameter
    descriptions included. ``args_schema`` is a permissive pydantic shell
    (every field ``Any``) kept for interface compatibility; it must NOT be
    used as a schema source because its round-trip drops all constraints.
    """
    def __init__(self, name: str, description: str, args_schema: Any, server_name: str,
                 input_schema: Optional[Dict[str, Any]] = None):
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self.server_name = server_name
        self.input_schema = input_schema or {}

    async def run(self, **kwargs) -> str:
        # Delegate back to the client to execute
        client = MCPClient() 
        return await client.execute_tool_on_server(self.server_name, self.name, kwargs)

class MCPClient:
    """
    Manages connections to MCP Servers (Stdio & SSE).
    """
    def __init__(self):
        self.servers = settings.MCP_SERVERS
        
    async def discover_tools(self) -> List[ExternalToolWrapper]:
        """
        Connect to all configured servers, list tools, and return wrappers.
        """
        wrappers = []
        
        for name, config in self.servers.items():
            try:
                logger.info(f"MCP: Discovering tools from {name}...")
                tools = await self._fetch_tools(name, config)
                for t in tools:
                    # Dynamically create Pydantic model for args
                    # Parse 'properties' and 'required' from JSON Schema
                    schema = t.inputSchema
                    properties = schema.get("properties", {})
                    required_fields = schema.get("required", [])
                    
                    fields = {}
                    for prop_name, prop_def in properties.items():
                        if prop_name in required_fields:
                            fields[prop_name] = (Any, ...) # Required
                        else:
                            fields[prop_name] = (Optional[Any], None) # Optional
                            
                    dummy_schema = create_model(f"{t.name}Args", **fields)
                    
                    wrapper = ExternalToolWrapper(
                        name=t.name,
                        description=t.description or "",
                        args_schema=dummy_schema,
                        server_name=name,
                        input_schema=schema,
                    )
                    wrappers.append(wrapper)
                    logger.info(f"MCP: Found tool {t.name} on {name}")
            except Exception as e:
                logger.error(f"MCP: Failed to discover {name}: {e}")
                
        return wrappers

    async def _fetch_tools(self, server_name: str, config: Dict[str, Any]) -> List[Tool]:
        """Connect, List, Disconnect."""
        transport = config.get("transport", "stdio") # Default to stdio
        
        if transport == "stdio":
            return await self._fetch_tools_stdio(config)
        elif transport == "sse":
            return await self._fetch_tools_sse(config)
        else:
            raise ValueError(f"Unknown transport: {transport}")

    async def _fetch_tools_stdio(self, config: Dict[str, Any]) -> List[Tool]:
        command = config.get("command")
        args = config.get("args")
        # Handle list vs string for args
        if isinstance(args, str):
            args = args.split()
        env = config.get("env")
        
        server_params = StdioServerParameters(command=command, args=args or [], env=env)
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools

    async def _fetch_tools_sse(self, config: Dict[str, Any]) -> List[Tool]:
        url = config.get("url")
        if not url:
            raise ValueError("SSE transport requires 'url'")
            
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools

    async def execute_tool_on_server(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Connect, Call, Disconnect."""
        if server_name not in self.servers:
            raise ValueError(f"Server {server_name} not configured.")
            
        config = self.servers[server_name]
        transport = config.get("transport", "stdio")
        
        logger.info(f"MCP: Executing {tool_name} on {server_name} ({transport})")
        
        try:
            if transport == "stdio":
                return await self._execute_stdio(config, tool_name, arguments)
            elif transport == "sse":
                return await self._execute_sse(config, tool_name, arguments)
            else:
                 raise ValueError(f"Unknown transport: {transport}")
                 
        except Exception as e:
            logger.error(f"MCP exec failed: {e}")
            raise e

    async def _execute_stdio(self, config: Dict[str, Any], tool_name: str, arguments: Dict[str, Any]) -> str:
        command = config.get("command")
        args = config.get("args")
        if isinstance(args, str):
            args = args.split()
        env = config.get("env")
        
        server_params = StdioServerParameters(command=command, args=args or [], env=env)
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await self._call_tool_session(session, tool_name, arguments)

    async def _execute_sse(self, config: Dict[str, Any], tool_name: str, arguments: Dict[str, Any]) -> str:
        url = config.get("url")
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await self._call_tool_session(session, tool_name, arguments)

    async def _call_tool_session(self, session: ClientSession, tool_name: str, arguments: Dict[str, Any]) -> str:
        result: CallToolResult = await session.call_tool(tool_name, arguments)
        
        output_text = []
        for content in result.content:
            if content.type == "text":
                output_text.append(content.text)
            elif content.type == "image":
                output_text.append(f"[Image]")
            elif content.type == "resource":
                output_text.append(f"[Resource]")
                
        final_out = "\n".join(output_text)
        if result.isError:
            return f"Error: {final_out}"
        return final_out

    # Generic execute that searches (if needed, but ExternalToolWrapper handles specifics)
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        raise NotImplementedError("Use execute_tool_on_server or the ToolWrapper")
