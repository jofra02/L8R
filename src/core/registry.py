from typing import Dict, List, Any, Optional
from src.core.interfaces import MCPToolInterface, CapabilityPackInterface
from src.mcp.client import MCPClient
from src.config import settings
import logging

logger = logging.getLogger(__name__)

class CapabilityRegistry:
    """
    Central registry for Capabilities (Tools, Playbooks, Normalizers).
    """
    _packs: Dict[str, CapabilityPackInterface] = {}
    _tools: Dict[str, MCPToolInterface] = {}
    
    @classmethod
    def register_pack(cls, pack: CapabilityPackInterface):
        """Register a capability pack."""
        logger.info(f"Registering pack: {pack.id}")
        cls._packs[pack.id] = pack
        
        for tool in pack.get_tools():
            cls._tools[tool.name] = tool
            
    @classmethod
    def get_tool(cls, name: str) -> MCPToolInterface:
        return cls._tools.get(name)
        
    @classmethod
    def _is_safe(cls, tool_name: str) -> bool:
        """Internal check against blocked keywords in config."""
        for kw in settings.SAFETY_BLOCKED_KEYWORDS:
             if kw in tool_name.lower():
                 return False
        return True

    @classmethod
    def list_tools(cls) -> List[MCPToolInterface]:
        """List all available tools (filtered by safety)."""
        return [t for t in cls._tools.values() if cls._is_safe(t.name)]

    @classmethod
    def search_tools(cls, query: str, limit: int = 3) -> List[MCPToolInterface]:
        """
        Semantic/Keyword search for tools (Filtered by safety).
        Currently implements a simple keyword match.
        """
        # TODO: Implement vector search via Qdrant if needed.
        # For now, simple keyword matching against name/description
        
        candidates = []
        scored_results = []
        tokens = query.lower().split()
        
        for tool in cls._tools.values():
            if not cls._is_safe(tool.name):
                continue

            score = 0
            name = tool.name.lower()
            desc = (tool.description or "").lower()
            
            # Exact phrase match bonus
            if query.lower() in name:
                score += 10
            elif query.lower() in desc:
                score += 5
            
            # Token matching
            for token in tokens:
                if len(token) < 3: # Skip short tokens
                    continue
                if token in name:
                    score += 3
                if token in desc:
                    score += 1
            
            if score > 0:
                scored_results.append((score, tool))
        
        # Sort by score descending
        scored_results.sort(key=lambda x: x[0], reverse=True)
        
        return [item[1] for item in scored_results[:limit]]

    @classmethod
    def get_playbook(cls, name: str) -> Dict[str, Any]:
        # Implementation to search playbooks across packs
        # Simple lookup for now
        for pack in cls._packs.values():
            for pb in pack.get_playbooks():
                if pb["id"] == name:
                    return pb
        return {}

    @classmethod
    def load_builtin_packs(cls):
        """Load default capability packs."""
        from src.capabilities.generic.pack import GenericCapabilityPack
        cls.register_pack(GenericCapabilityPack())

    @classmethod
    async def load_external_tools(cls):
        """Discover and load tools from configured MCP servers."""
        from src.mcp.client import MCPClient
        client = MCPClient()
        external_tools = await client.discover_tools()
        
        for tool in external_tools:
            logger.info(f"Registry: Registering external tool {tool.name} from {tool.server_name}")
            cls._tools[tool.name] = tool

    @classmethod
    async def index_tools_for_tenant(cls, customer_id: str):
        """Index all registered tools into Qdrant tool_catalog for a specific tenant."""
        from src.core.qdrant import vector_store
        
        tools = cls.list_tools()
        logger.info(f"Registry: Indexing {len(tools)} tools for tenant '{customer_id}'")
        
        for tool in tools:
            try:
                args_schema_json = {}
                if tool.args_schema:
                    args_schema_json = tool.args_schema.model_json_schema()
                
                server_name = getattr(tool, 'server_name', 'builtin')
                
                await vector_store.index_tool(
                    tool_name=tool.name,
                    description=tool.description or tool.name,
                    args_schema_json=args_schema_json,
                    server_name=server_name,
                    customer_id=customer_id,
                )
            except Exception as e:
                logger.warning(f"Registry: Failed to index tool {tool.name}: {e}")
        
        logger.info(f"Registry: Indexed {len(tools)} tools for tenant '{customer_id}'")

    @classmethod
    async def semantic_search_tools(cls, intent: str, customer_id: str, limit: int = 8) -> List[MCPToolInterface]:
        """
        Semantic search for tools by INTENT (what you want to accomplish).
        Returns actual tool objects from the registry, filtered by vector relevance.
        Falls back to keyword search if Qdrant is unavailable.
        """
        try:
            from src.core.qdrant import vector_store
            
            results = await vector_store.search_tool_catalog(
                intent=intent,
                customer_id=customer_id,
                limit=limit,
            )
            
            # Map back to actual tool objects
            matched_tools = []
            for payload in results:
                tool_name = payload.get("tool_name")
                tool = cls.get_tool(tool_name)
                if tool and cls._is_safe(tool.name):
                    matched_tools.append(tool)
            
            if matched_tools:
                logger.info(f"Registry: Semantic search for '{intent[:50]}' → {len(matched_tools)} tools")
                return matched_tools
            
        except Exception as e:
            logger.warning(f"Registry: Semantic search failed, falling back to keyword: {e}")
        
        # Fallback to keyword search
        return cls.search_tools(intent, limit=limit)

