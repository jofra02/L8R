import asyncio
import logging
import sys
import os

# Ensure the root path is in sys.path when running as a standalone script
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.core.qdrant import vector_store

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def clean_all_collections():
    """Wipes all collections and their points from Qdrant."""
    logger.info("Initializing Qdrant cleanup...")
    client = vector_store.client
    
    try:
        # Get all existing collections
        response = await client.get_collections()
        collections = [col.name for col in response.collections]
        
        if not collections:
            logger.info("No collections found to clean.")
            return

        logger.info(f"Found {len(collections)} collections: {collections}")
        
        # Delete each collection
        for collection_name in collections:
            logger.info(f"Deleting collection: {collection_name}")
            await client.delete_collection(collection_name=collection_name, timeout=10)
            logger.info(f"Collection '{collection_name}' successfully deleted.")
            
        logger.info("All collections have been wiped clean! (They will be recreated automatically when needed)")

    except Exception as e:
        logger.error(f"Failed to clean Qdrant collections: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(clean_all_collections())
