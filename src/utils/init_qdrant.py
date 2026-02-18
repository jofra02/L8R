import asyncio
import logging
from src.core.qdrant import vector_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_collections():
    logger.info("Initializing Qdrant Collections...")
    
    collections = [
        "knowledge_base",
        "evidence",
        "tool_knowledge",
        "resolved_tickets",
        "adaptive_fixes"
    ]
    
    for name in collections:
        try:
            logger.info(f"Checking collection: {name}")
            if await vector_store.client.collection_exists(name):
                 logger.info(f"✅ {name} already exists.")
            else:
                 logger.info(f"Creating {name}...")
                 await vector_store.ensure_collection(name)
                 logger.info(f"✅ {name} created.")
        except Exception as e:
            logger.error(f"❌ Failed to ensure {name}: {e}")

    logger.info("Closing Qdrant client...")
    await vector_store.client.close()
    logger.info("Done.")

if __name__ == "__main__":
    asyncio.run(init_collections())
