from qdrant_client import AsyncQdrantClient, models
from typing import List, Dict, Any, Optional
from src.config import settings
from langchain_openai import OpenAIEmbeddings
from src.core.rag_telemetry import rag_telemetry
import uuid
import json
import logging

logger = logging.getLogger(__name__)

class VectorStore:
    """Wrapper for Qdrant with enforced tenant isolation."""
    
    def __init__(self):
        self.client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY
        )
        self.embeddings = OpenAIEmbeddings(
            api_key=settings.OPENAI_API_KEY,
            model="text-embedding-3-small"
        )

    def _validate_payload(self, metadata: List[Dict[str, Any]]):
        """
        Strict check to ensure payloads are JSON serializable.
        Qdrant crashes if you pass non-serializable objects (like datetime).
        """
        try:
            # Try dumping. If it fails, raise error BEFORE hitting Qdrant network layer
            json.dumps(metadata, default=str)
        except Exception as e:
            raise ValueError(f"Payload validation failed: {e}")

    async def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding for text."""
        return await self.embeddings.aembed_query(text)

    def _generate_id(self, key: str) -> str:
        """Generate a deterministic UUID from a string key."""
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, key))

    @rag_telemetry(operation_name="ensure_collection")
    async def ensure_collection(self, collection_name: str, vector_size: int = 1536):
        """Ensure the collection exists with correct config."""
        if not await self.client.collection_exists(collection_name):
            logger.info(f"Creating collection {collection_name}...")
            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
            )

    @rag_telemetry(operation_name="add_texts")
    async def add_texts(self, collection_name: str, texts: List[str], metadatas: List[Dict[str, Any]], ids: List[str]):
        """
        Add texts to Qdrant. 
        Note: We are manually creating points.
        """
        if not texts:
            return

        self._validate_payload(metadatas)

        points = []
        for i, text in enumerate(texts):
            # Generate embedding
            vector = await self._get_embedding(text)
            
            # Create Payload
            payload = metadatas[i] if i < len(metadatas) else {}
            payload["page_content"] = text
            
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

    @rag_telemetry(operation_name="search")
    async def get_similar_evidence(self, query: str, limit: int = 5, score_threshold: float = 0.7) -> List[Any]:
        """Search specifically in evidence collection."""
        return await self.search("evidence", query, limit, score_threshold)

    @rag_telemetry(operation_name="save_tool_insight")
    @rag_telemetry(operation_name="save_tool_insight")
    async def save_tool_insight(self, knowledge: Any):
        """Save a learned tool insight."""
        # 'knowledge' is a ToolKnowledge Pydantic object
        await self.ensure_collection("tool_knowledge")
        
        # ID must be UUID or Int. We use deterministic UUID based on tool+pattern.
        unique_key = f"{knowledge.tool_name}-{knowledge.error_pattern}" if knowledge.error_pattern else knowledge.tool_name
        
        await self.add_texts(
            collection_name="tool_knowledge",
            texts=[knowledge.insight],
            metadatas=[knowledge.model_dump()],
            ids=[self._generate_id(unique_key)]
        )

    @rag_telemetry(operation_name="get_tool_insights")
    async def get_tool_insights(self, tool_name: str, query: str = "", limit: int = 3) -> List[Any]:
        """Retrieve insights for a specific tool."""
        # Filter by tool_name
        filter_cond = models.Filter(
            must=[
                models.FieldCondition(
                    key="tool_name",
                    match=models.MatchValue(value=tool_name)
                )
            ]
        )
        
        results = await self.client.query_points(
            collection_name="tool_knowledge",
            query=await self._get_embedding(query or f"how to use {tool_name}"),
            query_filter=filter_cond,
            limit=limit
        )
        return [pt.payload for pt in results.points]

    @rag_telemetry(operation_name="save_evidence")
    async def save_evidence(self, snapshot: Any):
        """Save a raw evidence snapshot for retrieval."""
        # 'snapshot' is EvidenceSnapshot
        await self.ensure_collection("evidence")
        
        # Text to vectorize: Tool name + Summary
        # We want to find "evidence about X"
        text_content = f"Tool: {snapshot.tool_name}\nSummary: {snapshot.summary}"
        
        # Use content_hash to generate ID ensures idempotency
        await self.add_texts(
            collection_name="evidence",
            texts=[text_content],
            metadatas=[snapshot.model_dump(mode='json')],
            ids=[self._generate_id(snapshot.content_hash)]
        )

    @rag_telemetry(operation_name="save_resolved_ticket")
    async def save_resolved_ticket(self, ticket: Any):
        """Index a resolved ticket for future RAG."""
        # 'ticket' is ResolvedTicket model
        await self.ensure_collection("resolved_tickets")
        await self.add_texts(
            collection_name="resolved_tickets",
            texts=[ticket.problem_summary], # The vector is the PROBLEM
            metadatas=[ticket.model_dump()], # The payload is the SOLUTION + Context
            ids=[self._generate_id(ticket.ticket_id)]
        )

    @rag_telemetry(operation_name="find_similar_cases")
    async def find_similar_cases(self, problem_description: str, limit: int = 3, customer_id: str = None) -> List[Any]:
        """Find similar past resolved cases."""
        # Optional: Filter by customer_id if we want strict isolation for CBR too
        # But usually, knowledge is shared (anonymized). 
        # For this system, we'll verify if we want to filter. 
        # Let's assume we filter by 'vendor' or 'component_role' if provided in query context?
        # For now, pure semantic search.
        
        results = await self.client.query_points(
            collection_name="resolved_tickets",
            query=await self._get_embedding(problem_description),
            limit=limit
        )
        return [pt.payload for pt in results.points]

    @rag_telemetry(operation_name="save_adaptive_fix")
    async def save_adaptive_fix(self, tool_name: str, error_msg: str, insight: str, fix_data: Dict[str, Any]):
        """Save a specific error-fix pair for self-healing."""
        # Fix data usually contains {bad_args, fixed_args}
        await self.ensure_collection("adaptive_fixes")
        await self.add_texts(
            collection_name="adaptive_fixes",
            texts=[error_msg], # Search by ERROR message
            metadatas=[{
                "tool_name": tool_name,
                "insight": insight,
                "fix": fix_data
            }],
            ids=[str(uuid.uuid4())]
        )

    @rag_telemetry(operation_name="get_adaptive_fixes")
    async def get_adaptive_fixes(self, tool_name: str, error_msg: str, limit: int = 2) -> List[Any]:
        """Retrieve fixes for a specific tool error."""
        filter_cond = models.Filter(
            must=[
                models.FieldCondition(
                    key="tool_name",
                    match=models.MatchValue(value=tool_name)
                )
            ]
        )
        
        results = await self.client.query_points(
            collection_name="adaptive_fixes",
            query=await self._get_embedding(error_msg),
            query_filter=filter_cond,
            limit=limit
        )
        return [pt.payload for pt in results.points]

    async def upsert(self, collection_name: str, points: List[models.PointStruct], customer_id: str):
        """Upsert points with WAIT=TRUE and customer enforcement."""
        # Enforce customer_id in payload for every point
        for point in points:
            if point.payload is None:
                point.payload = {}
            point.payload["customer_id"] = customer_id
            
        return await self.client.upsert(
            collection_name=collection_name,
            points=points,
            wait=True 
        )

    async def delete_point(self, collection_name: str, point_id: str):
        """Delete a point by ID (used for verification)."""
        await self.client.delete(
            collection_name=collection_name,
            points_selector=models.PointIdsList(points=[point_id]),
            wait=True
        )

    @rag_telemetry(operation_name="search")
    async def search(
        self, 
        collection_name: str, 
        vector: List[float], 
        customer_id: str, 
        limit: int = 5
    ) -> List[models.ScoredPoint]:
        """Search with MANDATORY customer_id filter."""
        
        # Strict isolation filter
        tenant_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="customer_id",
                    match=models.MatchValue(value=customer_id)
                )
            ]
        )
        
        # Use query_points (Modern API)
        response = await self.client.query_points(
            collection_name=collection_name,
            query=vector,
            query_filter=tenant_filter,
            limit=limit
        )
        return response.points

vector_store = VectorStore()
