"""Initialize Qdrant collections with proper indexes."""
import asyncio
import logging
from src.core.qdrant import vector_store
from src.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_collections():
    logger.info("Initializing Qdrant Collections with indexes...")
    await vector_store.ensure_all_collections()

    if settings.QDRANT_HYBRID_ENABLED:
        logger.info(
            f"Hybrid search enabled for collections: {settings.QDRANT_HYBRID_COLLECTIONS}"
        )
    else:
        logger.info("Hybrid search disabled. All collections use dense-only vectors.")

    logger.info("All collections and indexes initialized.")
    await vector_store.client.close()
    logger.info("Done.")

if __name__ == "__main__":
    asyncio.run(init_collections())
