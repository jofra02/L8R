from typing import Dict, List, Any, Optional
from src.core.interfaces import MCPToolInterface, CapabilityPackInterface
from src.mcp.client import MCPClient
from src.config import settings
from src.core.tool_categories import get_categories_prompt_block, get_all_category_slugs
import logging
import json

logger = logging.getLogger(__name__)

# --- Tool metadata extraction constants ---

_READ_METHODS = frozenset({
    "get",
})
_WRITE_METHODS = frozenset({
    "post", "put",
})

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

    # 2. Method: prefix match → suffix match → embedded _method_ scan
    method = "unknown"
    for m in (*_READ_METHODS, *_WRITE_METHODS):
        if name_lower.startswith(m + "_") or name_lower == m:
            method = m
            break
    if method == "unknown":
        # Suffix match: tool names like "fgt_cmdb_voip_profile_post"
        for m in (*_WRITE_METHODS, *_READ_METHODS):
            if name_lower.endswith("_" + m):
                method = m
                break
    if method == "unknown":
        best_pos = -1
        for m in (*_READ_METHODS, *_WRITE_METHODS):
            pos = name_lower.rfind(f"_{m}_")
            if pos > best_pos:
                best_pos = pos
                method = m

    # 3. Read-only: derived from method; description prefix as fallback
    read_only = method in _READ_METHODS or method == "unknown"
    if read_only and method == "unknown":
        desc_first = (description or "").strip().split(" ")[0].lower()
        if desc_first in ("create", "delete", "update", "remove", "modify"):
            read_only = False

    # 4. Categories: assigned by LLM in index_tools(), empty here
    categories = []

    # 5. Param count
    required = args_schema_json.get("required", []) if args_schema_json else []

    return {
        "vendor": vendor,
        "method": method,
        "read_only": read_only,
        "categories": categories,
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

    # Sentinel used for global (tenant-agnostic) tool catalog storage in Qdrant.
    TOOL_CATALOG_SENTINEL = "__global__"

    @classmethod
    async def index_tools(cls):
        """
        Index registered tools into Qdrant tool_catalog (global, shared across all tenants).
        Uses diff logic: only indexes tools not already present, avoiding
        unnecessary OpenAI Embedding API calls on warm startups.
        """
        from src.core.qdrant import vector_store

        cid = cls.TOOL_CATALOG_SENTINEL
        tools = cls.list_tools()
        registry_names = {t.name for t in tools}

        # Fast scroll — no embeddings, just payload field
        already_indexed = await vector_store.get_indexed_tool_names(cid)

        # Migration: detect old-format points without vendor metadata
        if already_indexed:
            needs_migration = await vector_store._check_catalog_needs_migration(cid)
            if needs_migration:
                logger.info("Registry: tool_catalog missing metadata fields — forcing full re-index.")
                already_indexed = set()

        new_tools = registry_names - already_indexed
        stale_tools = already_indexed - registry_names  # tools removed from MCP

        if not new_tools and not stale_tools:
            logger.info(
                f"Registry: tool_catalog up to date "
                f"({len(already_indexed)} tools). Skipping indexing."
            )
            return

        if stale_tools:
            logger.info(f"Registry: {len(stale_tools)} stale tools detected (not cleaning up yet)")

        logger.info(
            f"Registry: Indexing {len(new_tools)} NEW tools "
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
                dedup_key = f"{cid}-{tool.name}"

                texts.append(embed_text)
                metadatas.append({
                    "tool_name": tool.name,
                    "description": tool.description or tool.name,
                    "server_name": server_name,
                    "args_schema": args_schema_json,
                    "vendor": meta["vendor"],
                    "method": meta["method"],
                    "read_only": "true" if meta["read_only"] else "false",
                    "categories": [],  # filled by LLM below
                    "param_count": meta["param_count"],
                })
                ids.append(vector_store._generate_id(dedup_key))
            except Exception as e:
                logger.warning(f"Registry: Failed to prepare tool {tool.name}: {e}")

        # LLM-driven category assignment (batched 15-20 tools per prompt)
        if metadatas:
            llm_categories = await cls._assign_categories_via_llm(metadatas)
            for i, cats in enumerate(llm_categories):
                metadatas[i]["categories"] = cats

        if texts:
            await vector_store.batch_index_tools(
                texts=texts, metadatas=metadatas, ids=ids, customer_id=cid,
            )

        logger.info(f"Registry: Indexed {len(texts)}/{len(new_tools)} new tools (global)")

    @classmethod
    async def _assign_categories_via_llm(cls, metadatas: List[dict]) -> List[List[str]]:
        """Batch-assign IT domain categories to tools via LLM.

        Sends batches of 15-20 tools, each with name + truncated description.
        Returns a list of category lists, one per tool (same order as metadatas).
        """
        from langchain_core.messages import SystemMessage, HumanMessage
        from src.core.llm import LLMFactory

        llm = LLMFactory.get_model_for_agent("classifier")
        valid_slugs = get_all_category_slugs()
        taxonomy_block = get_categories_prompt_block()
        batch_size = 18
        all_categories: List[List[str]] = [[] for _ in metadatas]

        for batch_start in range(0, len(metadatas), batch_size):
            batch = metadatas[batch_start:batch_start + batch_size]
            tool_lines = []
            for m in batch:
                desc = (m.get("description") or m["tool_name"])[:150]
                tool_lines.append(f"- {m['tool_name']}: {desc}")
            tools_block = "\n".join(tool_lines)

            prompt = (
                f"Assign 1-5 IT domain categories to each tool from the taxonomy below.\n\n"
                f"## Taxonomy\n{taxonomy_block}\n\n"
                f"## Tools\n{tools_block}\n\n"
                f"Return ONLY valid JSON array. Each element: "
                f'{{\"tool\": \"<name>\", \"categories\": [\"<slug>\", ...]}}\n'
                f"Rules:\n"
                f"- Use ONLY slugs from the taxonomy above\n"
                f"- Assign 1-5 categories per tool based on what IT domain the tool operates in\n"
                f"- If uncertain, assign [\"general\"]\n"
                f"- Output nothing except the JSON array"
            )

            try:
                response = await llm.ainvoke([
                    SystemMessage(content="You are an IT tool classification specialist. Assign domain categories to tools."),
                    HumanMessage(content=prompt),
                ])
                raw = response.content.strip().replace("```json", "").replace("```", "")
                results = json.loads(raw)

                # Build lookup: tool_name → categories
                cat_map = {}
                for entry in results:
                    name = entry.get("tool", "")
                    cats = entry.get("categories", [])
                    # Validate slugs, cap at 5
                    valid_cats = [c for c in cats if c in valid_slugs][:5]
                    cat_map[name] = valid_cats if valid_cats else ["general"]

                # Map back to batch positions
                for i, m in enumerate(batch):
                    idx = batch_start + i
                    all_categories[idx] = cat_map.get(m["tool_name"], ["general"])

                logger.info(
                    f"Registry: LLM categorized batch {batch_start//batch_size + 1} "
                    f"({len(batch)} tools)"
                )
            except Exception as e:
                logger.warning(f"Registry: LLM category assignment failed for batch: {e}")
                for i in range(len(batch)):
                    all_categories[batch_start + i] = ["general"]

        return all_categories

    @classmethod
    async def semantic_search_tools(
        cls, intent: str, customer_id: str, limit: int = 8,
        vendor: str = None, method: str = None,
        read_only: bool = None, categories: List[str] = None,
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
                customer_id=cls.TOOL_CATALOG_SENTINEL,
                limit=limit,
                vendor=vendor,
                method=method,
                read_only=read_only,
                categories=categories,
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

