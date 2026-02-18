import asyncio
import logging
from qdrant_client import AsyncQdrantClient, models
from src.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def force_create():
    logger.info(f"Connecting to Qdrant at {settings.QDRANT_URL}...")
    client = AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY
    )
    
    collections_to_create = ["adaptive_fixes", "tool_knowledge", "evidence"]
    
    for name in collections_to_create:
        try:
            logger.info(f"Checking {name}...")
            exists = await client.collection_exists(name)
            if exists:
                logger.info(f"✅ {name} exists.")
            else:
                logger.info(f"Creating {name}...")
                await client.create_collection(
                    collection_name=name,
                    vectors_config=models.VectorParams(
                        size=1536,
                        distance=models.Distance.COSINE
                    )
                )
                logger.info(f"✅ {name} created successfully.")
        except Exception as e:
            logger.error(f"❌ Error with {name}: {e}")
            
    await client.close()
    logger.info("Done.")

if __name__ == "__main__":
    asyncio.run(force_create())
