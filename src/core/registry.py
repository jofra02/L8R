from typing import Dict, List, Any, Optional
from src.core.interfaces import MCPToolInterface, CapabilityPackInterface
from src.mcp.client import MCPClient
from src.config import settings
import logging

logger = logging.getLogger(__name__)

# --- Tool metadata extraction constants ---

_READ_METHODS = frozenset({
    "get",
})
_WRITE_METHODS = frozenset({
    "post", "put",
})

_CATEGORY_KEYWORDS = {
    "routing": ["route", "routing", "bgp", "ospf", "static_route", "rib"],
    "policy": ["policy", "rule", "acl", "firewall_rule", "security_rule", "filter"],
    "interface": ["interface", "port", "vlan", "link", "nic", "adapter"],
    "performance": ["cpu", "memory", "disk", "utilization", "load", "throughput", "latency", "metric"],
    "logs": ["log", "syslog", "event", "alert", "audit"],
    "config": ["config", "configuration", "setting"],
    "status": ["status", "health", "state", "uptime", "availability"],
    "inventory": ["inventory", "asset", "device", "host", "node"],
    "session": ["session", "connection", "arp", "mac_table", "neighbor"],
    "certificate": ["cert", "certificate", "ssl", "tls"],
    "dns": ["dns", "resolve", "domain", "nameserver"],
    "user": ["user", "account", "permission", "role", "auth"],
    "container": ["container", "pod", "kubernetes", "k8s", "docker"],
    "database": ["database", "db", "table", "replication", "replica"],
    "storage": ["storage", "volume", "disk", "mount", "filesystem"],
    "network": ["network", "subnet", "cidr", "ip", "nat", "vpn", "tunnel"],
}

_VENDOR_PATTERNS = {
    "fortinet": ["fortigate", "fortinet", "forti", "fgt"],
    "cisco": ["cisco", "ios", "nxos", "asa", "meraki"],
    "paloalto": ["paloalto", "pan", "panorama"],
    "aws": ["aws", "ec2", "s3", "lambda", "cloudwatch", "iam"],
    "azure": ["azure", "az_"],
    "gcp": ["gcp", "gcloud", "bigquery"],
    "vmware": ["vcenter", "vsphere", "vmware", "esxi"],
    "kubernetes": ["k8s", "kubectl", "kubernetes", "helm"],
    "linux": ["linux", "systemd", "journalctl"],
    "windows": ["windows", "powershell", "wmi", "ad_"],
    "docker": ["docker"],
    "postgresql": ["postgres", "pg_"],
    "mysql": ["mysql", "mariadb"],
    "mongodb": ["mongo", "mongodb"],
}


def _extract_tool_metadata(
    tool_name: str, description: str, args_schema_json: dict, server_name: str,
) -> dict:
    """Extract structured metadata from a tool's name, description, and schema."""
    name_lower = tool_name.lower()
    desc_lower = (description or "").lower()
    combined = f"{name_lower} {desc_lower}"

    # 1. Vendor: config mapping first, then name pattern
    vendor = settings.MCP_SERVER_VENDOR_MAP.get(server_name, "")
    if not vendor:
        for v, patterns in _VENDOR_PATTERNS.items():
            if any(p in name_lower for p in patterns):
                vendor = v
                break

    # 2. Method: prefix match first, then embedded _method_ scan
    method = "unknown"
    for m in (*_READ_METHODS, *_WRITE_METHODS):
        if name_lower.startswith(m + "_") or name_lower == m:
            method = m
            break
    if method == "unknown":
        best_pos = -1
        for m in (*_READ_METHODS, *_WRITE_METHODS):
            pos = name_lower.rfind(f"_{m}_")
            if pos > best_pos:
                best_pos = pos
                method = m

    # 3. Read-only: derived from method
    read_only = method in _READ_METHODS or method == "unknown"

    # 4. Category: keyword scan on name + description
    category = "general"
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            category = cat
            break

    # 5. Param count
    required = args_schema_json.get("required", []) if args_schema_json else []

    return {
        "vendor": vendor,
        "method": method,
        "read_only": read_only,
        "category": category,
        "param_count": len(required),
    }


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
        """
        Index registered tools into Qdrant tool_catalog for a specific tenant.
        Uses diff logic: only indexes tools not already present, avoiding
        unnecessary OpenAI Embedding API calls on warm startups.
        """
        from src.core.qdrant import vector_store
        
        tools = cls.list_tools()
        registry_names = {t.name for t in tools}
        
        # Fast scroll — no embeddings, just payload field
        already_indexed = await vector_store.get_indexed_tool_names(customer_id)

        # Migration: detect old-format points without vendor metadata
        if already_indexed:
            needs_migration = await vector_store._check_catalog_needs_migration(customer_id)
            if needs_migration:
                logger.info("Registry: tool_catalog missing metadata fields — forcing full re-index.")
                already_indexed = set()

        new_tools = registry_names - already_indexed
        stale_tools = already_indexed - registry_names  # tools removed from MCP
        
        if not new_tools and not stale_tools:
            logger.info(
                f"Registry: tool_catalog up to date for '{customer_id}' "
                f"({len(already_indexed)} tools). Skipping indexing."
            )
            return
        
        if stale_tools:
            logger.info(f"Registry: {len(stale_tools)} stale tools detected (not cleaning up yet)")
        
        logger.info(
            f"Registry: Indexing {len(new_tools)} NEW tools for '{customer_id}' "
            f"(skipping {len(already_indexed)} already indexed)"
        )
        
        tools_by_name = {t.name: t for t in tools}
        texts, metadatas, ids = [], [], []

        for tool_name in new_tools:
            tool = tools_by_name[tool_name]
            try:
                args_schema_json = {}
                if tool.args_schema:
                    args_schema_json = tool.args_schema.model_json_schema()

                server_name = getattr(tool, 'server_name', 'builtin')
                meta = _extract_tool_metadata(tool.name, tool.description or "", args_schema_json, server_name)

                # Build embed text (same logic as index_tool)
                args_summary = ""
                if args_schema_json:
                    props = args_schema_json.get("properties", {})
                    required = args_schema_json.get("required", [])
                    parts = []
                    for pname, pinfo in props.items():
                        req_tag = "(required)" if pname in required else "(optional)"
                        pdesc = pinfo.get("description", pinfo.get("title", pname))
                        parts.append(f"{pname} {req_tag}: {pdesc}")
                    args_summary = "Parameters: " + "; ".join(parts)

                embed_text = f"{tool.description or tool.name}. {args_summary}".strip()
                dedup_key = f"{customer_id}-{tool.name}"

                texts.append(embed_text)
                metadatas.append({
                    "tool_name": tool.name,
                    "description": tool.description or tool.name,
                    "server_name": server_name,
                    "args_schema": args_schema_json,
                    **meta,
                    "read_only": "true" if meta["read_only"] else "false",
                })
                ids.append(vector_store._generate_id(dedup_key))
            except Exception as e:
                logger.warning(f"Registry: Failed to prepare tool {tool.name}: {e}")

        if texts:
            await vector_store.batch_index_tools(
                texts=texts, metadatas=metadatas, ids=ids, customer_id=customer_id,
            )

        logger.info(f"Registry: Indexed {len(texts)}/{len(new_tools)} new tools for '{customer_id}'")

    @classmethod
    async def semantic_search_tools(
        cls, intent: str, customer_id: str, limit: int = 8,
        vendor: str = None, method: str = None,
        read_only: bool = None, category: str = None,
    ) -> List[MCPToolInterface]:
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
                vendor=vendor,
                method=method,
                read_only=read_only,
                category=category,
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

