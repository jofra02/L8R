"""
Hybrid migration script: nuke all collections, recreate with hybrid config, re-seed KB.

Usage:
    uv run python -m src.utils.clean_and_reseed --dir <kb_dir> --customer-id <id>

Prerequisites:
    Set QDRANT_HYBRID_ENABLED=true in .env before running.

Steps performed:
    1. Delete all existing Qdrant collections
    2. Recreate collections with hybrid vector config (if enabled)
    3. Re-seed knowledge base from directory
    4. Tool catalog re-indexes automatically on first ticket
"""
import asyncio
import sys
import logging
from src.utils.clean_qdrant import clean_all_collections
from src.utils.init_qdrant import init_collections
from src.utils.seed_kb import seed_kb

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def clean_and_reseed(kb_dir: str, customer_id: str):
    logger.info("=== Step 1: Nuking all collections ===")
    await clean_all_collections()

    logger.info("=== Step 2: Recreating collections with current config ===")
    await init_collections()

    logger.info("=== Step 3: Re-seeding knowledge base ===")
    await seed_kb(kb_dir, customer_id)

    logger.info("=== Migration complete ===")
    logger.info("Tool catalog will re-index automatically on the next ticket ingestion.")


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python -m src.utils.clean_and_reseed --dir <kb_dir> --customer-id <id>")
        sys.exit(1)

    args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    dir_path = args.get("--dir")
    cid = args.get("--customer-id")

    if dir_path and cid:
        asyncio.run(clean_and_reseed(dir_path, cid))
    else:
        print("Invalid arguments. Required: --dir and --customer-id")
