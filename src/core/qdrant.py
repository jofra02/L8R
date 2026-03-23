from qdrant_client import AsyncQdrantClient, models
from typing import List, Dict, Any, Optional
from src.config import settings
from langchain_openai import OpenAIEmbeddings
from src.core.rag_telemetry import rag_telemetry
from datetime import datetime, timezone
import uuid
import json
import logging

logger = logging.getLogger(__name__)

# Project-specific namespace for deterministic UUIDs
_NAMESPACE = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

# Collections and their required payload indexes
COLLECTION_INDEXES: Dict[str, List[tuple]] = {
    "knowledge_base": [
        ("customer_id", models.PayloadSchemaType.KEYWORD),
        ("source", models.PayloadSchemaType.KEYWORD),
        ("source_type", models.PayloadSchemaType.KEYWORD),
        ("created_at", models.PayloadSchemaType.DATETIME),
    ],
    "evidence": [
        ("customer_id", models.PayloadSchemaType.KEYWORD),
        ("tool_name", models.PayloadSchemaType.KEYWORD),
        ("source_type", models.PayloadSchemaType.KEYWORD),
        ("run_id", models.PayloadSchemaType.KEYWORD),
        ("created_at", models.PayloadSchemaType.DATETIME),
    ],
    "tool_knowledge": [
        ("customer_id", models.PayloadSchemaType.KEYWORD),
        ("tool_name", models.PayloadSchemaType.KEYWORD),
        ("vendor", models.PayloadSchemaType.KEYWORD),
        ("source_type", models.PayloadSchemaType.KEYWORD),
        ("created_at", models.PayloadSchemaType.DATETIME),
    ],
    "resolved_tickets": [
        ("customer_id", models.PayloadSchemaType.KEYWORD),
        ("vendor", models.PayloadSchemaType.KEYWORD),
        ("component_role", models.PayloadSchemaType.KEYWORD),
        ("resolution_status", models.PayloadSchemaType.KEYWORD),
        ("source_type", models.PayloadSchemaType.KEYWORD),
        ("created_at", models.PayloadSchemaType.DATETIME),
    ],
    "adaptive_fixes": [
        ("customer_id", models.PayloadSchemaType.KEYWORD),
        ("tool_name", models.PayloadSchemaType.KEYWORD),
        ("source_type", models.PayloadSchemaType.KEYWORD),
        ("created_at", models.PayloadSchemaType.DATETIME),
    ],
    "tool_catalog": [
        ("customer_id", models.PayloadSchemaType.KEYWORD),
        ("tool_name", models.PayloadSchemaType.KEYWORD),
        ("server_name", models.PayloadSchemaType.KEYWORD),
        ("vendor", models.PayloadSchemaType.KEYWORD),
        ("method", models.PayloadSchemaType.KEYWORD),
        ("read_only", models.PayloadSchemaType.KEYWORD),
        ("category", models.PayloadSchemaType.KEYWORD),
        ("source_type", models.PayloadSchemaType.KEYWORD),
    ],
}


class VectorStore:
    """Wrapper for Qdrant with enforced tenant isolation and standard metadata."""
    
    def __init__(self):
        self.client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            timeout=settings.QDRANT_TIMEOUT,
        )
        self.embeddings = OpenAIEmbeddings(
            api_key=settings.OPENAI_API_KEY,
            model=settings.EMBEDDING_MODEL,
        )
        self._initialized_collections: set = set()

    # ─── Initialization ────────────────────────────────────────────

    async def ensure_collection(self, collection_name: str, vector_size: int = 1536):
        """Ensure collection exists with vector config and payload indexes. Idempotent."""
        if collection_name in self._initialized_collections:
            return  # Already checked this runtime session
        
        if not await self.client.collection_exists(collection_name):
            logger.info(f"Creating collection '{collection_name}'...")
            if self._is_hybrid(collection_name):
                await self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config={
                        "dense": models.VectorParams(
                            size=settings.EMBEDDING_DIMENSIONS,
                            distance=models.Distance.COSINE,
                        ),
                    },
                    sparse_vectors_config={
                        "bm25": models.SparseVectorParams(
                            modifier=models.Modifier.IDF,
                        ),
                    },
                    on_disk_payload=settings.QDRANT_ON_DISK_PAYLOAD,
                )
            else:
                await self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
                )

        # Create payload indexes (idempotent — Qdrant ignores if exists)
        indexes = COLLECTION_INDEXES.get(collection_name, [
            ("customer_id", models.PayloadSchemaType.KEYWORD),
            ("source_type", models.PayloadSchemaType.KEYWORD),
            ("created_at", models.PayloadSchemaType.DATETIME),
        ])
        for field_name, field_schema in indexes:
            try:
                if field_name == "customer_id":
                    await self.client.create_payload_index(
                        collection_name=collection_name,
                        field_name=field_name,
                        field_schema=models.KeywordIndexParams(
                            type=models.KeywordIndexType.KEYWORD,
                            is_tenant=True,
                        ),
                    )
                else:
                    await self.client.create_payload_index(
                        collection_name=collection_name,
                        field_name=field_name,
                        field_schema=field_schema,
                    )
            except Exception:
                pass  # Index already exists or not applicable

        self._initialized_collections.add(collection_name)

    async def ensure_all_collections(self):
        """Bootstrap all project collections at startup."""
        for name in COLLECTION_INDEXES:
            await self.ensure_collection(name)

    # ─── Internal Helpers ──────────────────────────────────────────

    async def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single query text."""
        return await self.embeddings.aembed_query(text)

    async def _batch_embed(self, texts: List[str]) -> List[List[float]]:
        """Batch-embed texts, respecting batch size limits."""
        batch_size = settings.EMBEDDING_BATCH_SIZE
        all_vectors = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            vectors = await self.embeddings.aembed_documents(batch)
            all_vectors.extend(vectors)
        return all_vectors

    @staticmethod
    def _generate_id(key: str) -> str:
        """Generate a deterministic UUID from a string key."""
        return str(uuid.uuid5(_NAMESPACE, key))

    @staticmethod
    def _now_iso() -> str:
        """Current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def _validate_payload(self, metadata: List[Dict[str, Any]]):
        """Strict check to ensure payloads are JSON serializable."""
        try:
            json.dumps(metadata, default=str)
        except Exception as e:
            raise ValueError(f"Payload validation failed: {e}")

    # ─── Hybrid / Sparse Helpers ─────────────────────────────────

    def _is_hybrid(self, collection_name: str) -> bool:
        return (
            settings.QDRANT_HYBRID_ENABLED
            and collection_name in settings.QDRANT_HYBRID_COLLECTIONS
        )

    def _get_sparse_model(self):
        """Lazy-init fastembed BM25 model."""
        if not hasattr(self, '_sparse_model'):
            from fastembed import SparseTextEmbedding
            self._sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
        return self._sparse_model

    def _sparse_embed_query(self, text: str) -> models.SparseVector:
        """Generate BM25 sparse vector for a single query."""
        model = self._get_sparse_model()
        results = list(model.query_embed(text))
        if results:
            return models.SparseVector(
                indices=results[0].indices.tolist(),
                values=results[0].values.tolist(),
            )
        return models.SparseVector(indices=[], values=[])

    def _sparse_embed_documents(self, texts: List[str]) -> List[models.SparseVector]:
        """Generate BM25 sparse vectors for multiple documents."""
        model = self._get_sparse_model()
        results = list(model.passage_embed(texts))
        return [
            models.SparseVector(
                indices=r.indices.tolist(),
                values=r.values.tolist(),
            )
            for r in results
        ]

    def _build_tenant_filter(self, customer_id: str, extra_must: list = None) -> models.Filter:
        """Build a Qdrant filter with mandatory tenant isolation."""
        must = [
            models.FieldCondition(
                key="customer_id",
                match=models.MatchValue(value=customer_id)
            )
        ]
        if extra_must:
            must.extend(extra_must)
        return models.Filter(must=must)

    # ─── Core Write (Unified) ──────────────────────────────────────

    @rag_telemetry(operation_name="add_texts")
    async def add_texts(
        self,
        collection_name: str,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str],
        customer_id: str,
        source_type: str,
        run_id: Optional[str] = None,
    ):
        """
        Unified insert path. Every point gets standard metadata injected:
        customer_id, created_at, source_type, run_id.
        """
        if not texts:
            return

        self._validate_payload(metadatas)
        await self.ensure_collection(collection_name)

        now = self._now_iso()
        vectors = await self._batch_embed(texts)
        hybrid = self._is_hybrid(collection_name)
        sparse_vectors = self._sparse_embed_documents(texts) if hybrid else None

        points = []
        for i, text in enumerate(texts):
            payload = metadatas[i] if i < len(metadatas) else {}
            payload["page_content"] = text
            payload["customer_id"] = customer_id
            payload["source_type"] = source_type
            payload["created_at"] = now
            if run_id:
                payload["run_id"] = run_id

            point_id = ids[i] if i < len(ids) else str(uuid.uuid4())

            if hybrid:
                vector_data = {
                    "dense": vectors[i],
                    "bm25": sparse_vectors[i],
                }
            else:
                vector_data = vectors[i]

            points.append(models.PointStruct(
                id=point_id,
                vector=vector_data,
                payload=payload
            ))
            
        return await self.client.upsert(
            collection_name=collection_name,
            points=points,
            wait=True
        )

    # ─── Core Search (Unified) ─────────────────────────────────────

    @rag_telemetry(operation_name="search")
    async def search(
        self, 
        collection_name: str, 
        query_text: str, 
        customer_id: str, 
        limit: int = 5,
        score_threshold: float = 0.0,
        extra_filter: list = None,
    ) -> List[models.ScoredPoint]:
        """Search with MANDATORY customer_id filter and optional extra filters."""
        await self.ensure_collection(collection_name)
        tenant_filter = self._build_tenant_filter(customer_id, extra_must=extra_filter)
        threshold = score_threshold if score_threshold > 0 else None
        search_params = models.SearchParams(
            hnsw_ef=settings.QDRANT_HNSW_EF,
            indexed_only=settings.QDRANT_INDEXED_ONLY,
        )

        try:
            if self._is_hybrid(collection_name):
                dense_vector = await self._get_embedding(query_text)
                sparse_vector = self._sparse_embed_query(query_text)
                response = await self.client.query_points(
                    collection_name=collection_name,
                    prefetch=[
                        models.Prefetch(
                            query=dense_vector,
                            using="dense",
                            limit=limit * 3,
                        ),
                        models.Prefetch(
                            query=sparse_vector,
                            using="bm25",
                            limit=limit * 3,
                        ),
                    ],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    query_filter=tenant_filter,
                    limit=limit,
                    score_threshold=threshold,
                    search_params=search_params,
                )
            else:
                vector = await self._get_embedding(query_text)
                response = await self.client.query_points(
                    collection_name=collection_name,
                    query=vector,
                    query_filter=tenant_filter,
                    limit=limit,
                    score_threshold=threshold,
                    search_params=search_params,
                )
            return response.points
        except Exception as e:
            if "Not found" in str(e) or "doesn't exist" in str(e):
                return []
            raise

    # ─── Domain Methods: Evidence ──────────────────────────────────

    @rag_telemetry(operation_name="save_evidence")
    async def save_evidence(self, snapshot: Any, customer_id: str, run_id: str = None):
        """Save a raw evidence snapshot for retrieval."""
        text_content = f"Tool: {snapshot.tool_name}\nSummary: {snapshot.summary}"
        
        metadata = snapshot.model_dump(mode='json')
        # Remove large fields from payload to keep it lean
        metadata.pop("tool_args", None)
        
        await self.add_texts(
            collection_name="evidence",
            texts=[text_content],
            metadatas=[metadata],
            ids=[self._generate_id(snapshot.content_hash)],
            customer_id=customer_id,
            source_type="evidence",
            run_id=run_id,
        )

    @rag_telemetry(operation_name="get_similar_evidence")
    async def get_similar_evidence(
        self, query: str, customer_id: str, limit: int = 5,
        score_threshold: float = None,
    ) -> List[Any]:
        """Search evidence collection with tenant isolation."""
        threshold = score_threshold if score_threshold is not None else settings.QDRANT_SCORE_EVIDENCE
        results = await self.search(
            "evidence", query, customer_id, limit, threshold
        )
        return [pt.payload for pt in results]

    # ─── Domain Methods: Knowledge Base ──────────────────────────

    @rag_telemetry(operation_name="search_knowledge_base")
    async def search_knowledge_base(
        self, query: str, customer_id: str, limit: int = 3,
        score_threshold: float = None,
    ) -> List[Dict[str, Any]]:
        """Search knowledge base for relevant articles with tenant isolation."""
        threshold = score_threshold or settings.QDRANT_SCORE_KNOWLEDGE_BASE
        results = await self.search(
            "knowledge_base", query, customer_id, limit, threshold
        )
        return [pt.payload for pt in results]

    # ─── Domain Methods: Tool Knowledge ────────────────────────────

    @rag_telemetry(operation_name="save_tool_insight")
    async def save_tool_insight(self, knowledge: Any, customer_id: str = "global"):
        """Save a learned tool insight."""
        unique_key = f"{knowledge.tool_name}-{knowledge.error_pattern}" if knowledge.error_pattern else knowledge.tool_name

        await self.add_texts(
            collection_name="tool_knowledge",
            texts=[knowledge.insight],
            metadatas=[knowledge.model_dump(mode='json')],
            ids=[self._generate_id(unique_key)],
            customer_id=customer_id,
            source_type="tool_insight",
        )

    @rag_telemetry(operation_name="get_tool_insights")
    async def get_tool_insights(
        self, tool_name: str, customer_id: str = "global", query: str = "", limit: int = 3
    ) -> List[Any]:
        """Retrieve insights for a specific tool, filtered by tool_name."""
        extra_filter = [
            models.FieldCondition(
                key="tool_name",
                match=models.MatchValue(value=tool_name)
            )
        ]
        results = await self.search(
            "tool_knowledge",
            query or f"how to use {tool_name}",
            customer_id,
            limit,
            extra_filter=extra_filter,
        )
        return [pt.payload for pt in results]

    # ─── Domain Methods: Resolved Tickets (CBR) ───────────────────

    @rag_telemetry(operation_name="save_resolved_ticket")
    async def save_resolved_ticket(self, ticket: Any, customer_id: str):
        """Index a resolved ticket for future RAG."""
        await self.add_texts(
            collection_name="resolved_tickets",
            texts=[ticket.problem_summary],
            metadatas=[ticket.model_dump(mode='json')],
            ids=[self._generate_id(ticket.ticket_id)],
            customer_id=customer_id,
            source_type="resolved_case",
        )

    @rag_telemetry(operation_name="find_similar_cases")
    async def find_similar_cases(
        self, problem_description: str, customer_id: str, limit: int = 3
    ) -> List[Any]:
        """Find similar past resolved cases with tenant isolation."""
        results = await self.search(
            "resolved_tickets", problem_description, customer_id, limit
        )
        return [pt.payload for pt in results]

    # ─── Domain Methods: Adaptive Fixes ────────────────────────────

    @rag_telemetry(operation_name="save_adaptive_fix")
    async def save_adaptive_fix(
        self, tool_name: str, error_msg: str, insight: str, fix_data: Dict[str, Any],
        customer_id: str
    ):
        """Save a specific error-fix pair for self-healing. Deterministic ID for dedup."""
        import re
        # Normalize variable data (IPs, UUIDs) for dedup so same-class errors
        # within a tenant collapse but different tenants stay separate.
        normalized_err = re.sub(r'\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?', '<IP>', error_msg[:100])
        normalized_err = re.sub(
            r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
            '<UUID>', normalized_err
        )
        dedup_key = f"{customer_id}-{tool_name}-{normalized_err}"

        await self.add_texts(
            collection_name="adaptive_fixes",
            texts=[error_msg],
            metadatas=[{
                "tool_name": tool_name,
                "insight": insight,
                "fix": fix_data
            }],
            ids=[self._generate_id(dedup_key)],
            customer_id=customer_id,
            source_type="adaptive_fix",
        )

    @rag_telemetry(operation_name="get_adaptive_fixes")
    async def get_adaptive_fixes(
        self, tool_name: str, error_msg: str, customer_id: str, limit: int = 2
    ) -> List[Any]:
        """Retrieve fixes for a specific tool error with score threshold filtering."""
        extra_filter = [
            models.FieldCondition(
                key="tool_name",
                match=models.MatchValue(value=tool_name)
            )
        ]
        results = await self.search(
            "adaptive_fixes", error_msg, customer_id, limit,
            score_threshold=settings.QDRANT_SCORE_ADAPTIVE_FIXES,
            extra_filter=extra_filter,
        )
        return [pt.payload for pt in results]

    async def delete_point(self, collection_name: str, point_id: str):
        """Delete a point by ID."""
        await self.client.delete(
            collection_name=collection_name,
            points_selector=models.PointIdsList(points=[point_id]),
            wait=True
        )

    # ─── Domain Methods: Tool Catalog ──────────────────────────────

    @rag_telemetry(operation_name="index_tool")
    async def index_tool(
        self, tool_name: str, description: str, args_schema_json: dict,
        server_name: str, customer_id: str,
        vendor: str = "", method: str = "", read_only: bool = True,
        category: str = "", param_count: int = 0,
    ):
        """
        Index a tool by its DESCRIPTION (semantic content), not its name.
        The vector is built from: description + summarized args.
        Deterministic ID per (customer_id, tool_name) for idempotent re-indexing.
        """
        # Build rich text for embedding: description + args summary
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

        embed_text = f"{description}. {args_summary}".strip()

        dedup_key = f"{customer_id}-{tool_name}"

        await self.add_texts(
            collection_name="tool_catalog",
            texts=[embed_text],
            metadatas=[{
                "tool_name": tool_name,
                "description": description,
                "server_name": server_name,
                "args_schema": args_schema_json,
                "vendor": vendor,
                "method": method,
                "read_only": "true" if read_only else "false",
                "category": category,
                "param_count": param_count,
            }],
            ids=[self._generate_id(dedup_key)],
            customer_id=customer_id,
            source_type="tool_catalog",
        )

    @rag_telemetry(operation_name="batch_index_tools")
    async def batch_index_tools(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str],
        customer_id: str,
        chunk_size: int = 200,
    ):
        """Batch-index tool catalog entries via add_texts. Embeddings are batched
        internally by EMBEDDING_BATCH_SIZE; upserts are chunked to stay under
        Qdrant's payload size limit."""
        for i in range(0, len(texts), chunk_size):
            await self.add_texts(
                collection_name="tool_catalog",
                texts=texts[i:i + chunk_size],
                metadatas=metadatas[i:i + chunk_size],
                ids=ids[i:i + chunk_size],
                customer_id=customer_id,
                source_type="tool_catalog",
            )

    async def get_indexed_tool_names(self, customer_id: str) -> set:
        """
        Return the set of tool_names already indexed in tool_catalog for a tenant.
        Uses scroll (no embedding call) — cheap and fast.
        """
        await self.ensure_collection("tool_catalog")
        
        indexed = set()
        offset = None
        tenant_filter = self._build_tenant_filter(customer_id)
        
        while True:
            results, next_offset = await self.client.scroll(
                collection_name="tool_catalog",
                scroll_filter=tenant_filter,
                limit=250,
                offset=offset,
                with_payload=["tool_name"],
                with_vectors=False,
            )
            for pt in results:
                name = pt.payload.get("tool_name")
                if name:
                    indexed.add(name)
            
            if next_offset is None:
                break
            offset = next_offset
        
        return indexed

    # Tool catalog is global (shared across all tenants).
    # All tools are indexed under this sentinel; per-tenant restrictions will be added later.
    TOOL_CATALOG_GLOBAL_ID = "__global__"

    @rag_telemetry(operation_name="search_tool_catalog")
    async def search_tool_catalog(
        self, intent: str, customer_id: str, limit: int = 8,
        score_threshold: float = None,
        vendor: str = None,
        method: str = None,
        read_only: bool = None,
        category: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search for tools by INTENT description.
        Returns tool payloads sorted by relevance.
        Optional keyword filters narrow results before vector scoring.
        """
        # Tool catalog is global — override per-tenant customer_id
        customer_id = self.TOOL_CATALOG_GLOBAL_ID
        threshold = score_threshold if score_threshold is not None else settings.QDRANT_SCORE_TOOL_CATALOG

        extra_filter = []
        if vendor:
            extra_filter.append(models.FieldCondition(
                key="vendor", match=models.MatchValue(value=vendor.lower())
            ))
        if method:
            extra_filter.append(models.FieldCondition(
                key="method", match=models.MatchValue(value=method.lower())
            ))
        if read_only is not None:
            extra_filter.append(models.FieldCondition(
                key="read_only", match=models.MatchValue(value="true" if read_only else "false")
            ))
        if category:
            extra_filter.append(models.FieldCondition(
                key="category", match=models.MatchValue(value=category.lower())
            ))

        logger.debug(f"search_tool_catalog: query='{intent}', vendor={vendor}, read_only={read_only}, category={category}")
        results = await self.search(
            "tool_catalog", intent, customer_id, limit,
            score_threshold=threshold,
            extra_filter=extra_filter if extra_filter else None,
        )
        return [pt.payload for pt in results]

    async def _check_catalog_needs_migration(self, customer_id: str) -> bool:
        """Check if tool_catalog points have the vendor field (metadata enrichment migration)."""
        await self.ensure_collection("tool_catalog")
        tenant_filter = self._build_tenant_filter(customer_id)
        results, _ = await self.client.scroll(
            collection_name="tool_catalog",
            scroll_filter=tenant_filter,
            limit=1,
            with_payload=["vendor"],
            with_vectors=False,
        )
        if not results:
            return False
        return "vendor" not in results[0].payload or results[0].payload.get("vendor") == ""


vector_store = VectorStore()
