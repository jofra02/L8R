"""Initialize Qdrant collections with proper indexes."""
import asyncio
import logging
from src.core.qdrant import vector_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_collections():
    logger.info("Initializing Qdrant Collections with indexes...")
    await vector_store.ensure_all_collections()
    logger.info("All collections and indexes initialized.")
    await vector_store.client.close()
    logger.info("Done.")

if __name__ == "__main__":
    asyncio.run(init_collections())
