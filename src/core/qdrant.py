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
}


class VectorStore:
    """Wrapper for Qdrant with enforced tenant isolation and standard metadata."""
    
    def __init__(self):
        self.client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY
        )
        self.embeddings = OpenAIEmbeddings(
            api_key=settings.OPENAI_API_KEY,
            model="text-embedding-3-small"
        )
        self._initialized_collections: set = set()

    # ─── Initialization ────────────────────────────────────────────

    async def ensure_collection(self, collection_name: str, vector_size: int = 1536):
        """Ensure collection exists with vector config and payload indexes. Idempotent."""
        if collection_name in self._initialized_collections:
            return  # Already checked this runtime session
        
        if not await self.client.collection_exists(collection_name):
            logger.info(f"Creating collection '{collection_name}'...")
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
        """Generate embedding for text."""
        return await self.embeddings.aembed_query(text)

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
        points = []
        for i, text in enumerate(texts):
            vector = await self._get_embedding(text)
            
            payload = metadatas[i] if i < len(metadatas) else {}
            # Inject standard fields
            payload["page_content"] = text
            payload["customer_id"] = customer_id
            payload["source_type"] = source_type
            payload["created_at"] = now
            if run_id:
                payload["run_id"] = run_id
            
            point_id = ids[i] if i < len(ids) else str(uuid.uuid4())
            
            points.append(models.PointStruct(
                id=point_id,
                vector=vector,
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
        vector = await self._get_embedding(query_text)
        tenant_filter = self._build_tenant_filter(customer_id, extra_must=extra_filter)
        
        try:
            response = await self.client.query_points(
                collection_name=collection_name,
                query=vector,
                query_filter=tenant_filter,
                limit=limit,
                score_threshold=score_threshold if score_threshold > 0 else None,
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
        self, query: str, customer_id: str, limit: int = 5, score_threshold: float = 0.7
    ) -> List[Any]:
        """Search evidence collection with tenant isolation."""
        results = await self.search(
            "evidence", query, customer_id, limit, score_threshold
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
        customer_id: str = "global"
    ):
        """Save a specific error-fix pair for self-healing. Deterministic ID for dedup."""
        dedup_key = f"{tool_name}-{error_msg[:100]}"
        
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
        self, tool_name: str, error_msg: str, customer_id: str = "global", limit: int = 2
    ) -> List[Any]:
        """Retrieve fixes for a specific tool error."""
        extra_filter = [
            models.FieldCondition(
                key="tool_name",
                match=models.MatchValue(value=tool_name)
            )
        ]
        results = await self.search(
            "adaptive_fixes", error_msg, customer_id, limit, extra_filter=extra_filter
        )
        return [pt.payload for pt in results]

    # ─── Legacy Compat: Direct Upsert ──────────────────────────────

    async def upsert_raw(self, collection_name: str, points: List[models.PointStruct], customer_id: str):
        """Direct upsert for pre-built points (e.g., seed_kb). Injects customer_id."""
        await self.ensure_collection(collection_name)
        for point in points:
            if point.payload is None:
                point.payload = {}
            point.payload["customer_id"] = customer_id
            point.payload.setdefault("created_at", self._now_iso())
            point.payload.setdefault("source_type", "kb_chunk")
        
        return await self.client.upsert(
            collection_name=collection_name,
            points=points,
            wait=True 
        )

    async def delete_point(self, collection_name: str, point_id: str):
        """Delete a point by ID."""
        await self.client.delete(
            collection_name=collection_name,
            points_selector=models.PointIdsList(points=[point_id]),
            wait=True
        )


vector_store = VectorStore()
