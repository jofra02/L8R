from qdrant_client import AsyncQdrantClient, models
from typing import List, Dict, Any, Optional
from src.config import settings

class VectorStore:
    """Wrapper for Qdrant with enforced tenant isolation."""
    
    def __init__(self):
        self.client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY
        )

    async def ensure_collection(self, collection_name: str, vector_size: int = 1536):
        """Ensure the collection exists with correct config."""
        if not await self.client.collection_exists(collection_name):
            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
            )

    async def upsert(self, collection_name: str, points: List[models.PointStruct], customer_id: str):
        """Upsert points, enforcing customer_id in payload."""
        # Enforce customer_id in payload for every point
        for point in points:
            if point.payload is None:
                point.payload = {}
            point.payload["customer_id"] = customer_id
            
        await self.client.upsert(
            collection_name=collection_name,
            points=points
        )

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
        
        return await self.client.search(
            collection_name=collection_name,
            query_vector=vector,
            query_filter=tenant_filter,
            limit=limit
        )

vector_store = VectorStore()
