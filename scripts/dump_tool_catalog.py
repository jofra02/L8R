"""
Dump all tool_catalog entries from Qdrant for a given tenant into a JSON file.

Usage:
    uv run python scripts/dump_tool_catalog.py --customer-id fake_client [--output dump.json]

Uses AsyncQdrantClient directly (no embedding/OpenAI key required).
"""
import argparse
import asyncio
import json
import os
import sys

from qdrant_client import AsyncQdrantClient, models


async def dump_catalog(customer_id: str, output_path: str, qdrant_url: str):
    client = AsyncQdrantClient(url=qdrant_url, timeout=30)

    tenant_filter = models.Filter(must=[
        models.FieldCondition(
            key="customer_id",
            match=models.MatchValue(value=customer_id),
        )
    ])

    tools = []
    offset = None

    while True:
        results, next_offset = await client.scroll(
            collection_name="tool_catalog",
            scroll_filter=tenant_filter,
            limit=250,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for pt in results:
            payload = pt.payload or {}
            tools.append({
                "tool_name": payload.get("tool_name", ""),
                "description": payload.get("description", ""),
                "server_name": payload.get("server_name", ""),
                "vendor": payload.get("vendor", ""),
                "method": payload.get("method", ""),
                "read_only": payload.get("read_only", ""),
                "category": payload.get("category", ""),
                "param_count": payload.get("param_count", 0),
                "args_schema": payload.get("args_schema", {}),
                "page_content": payload.get("page_content", ""),
            })

        if next_offset is None:
            break
        offset = next_offset

    await client.close()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(tools, f, indent=2, ensure_ascii=False)

    print(f"Dumped {len(tools)} tools to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Dump tool_catalog from Qdrant")
    parser.add_argument("--customer-id", required=True, help="Tenant customer_id to filter by")
    parser.add_argument("--output", default=None, help="Output JSON path (default: tool_catalog_dump_<cid>.json)")
    args = parser.parse_args()

    output = args.output or f"tool_catalog_dump_{args.customer_id}.json"
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")

    asyncio.run(dump_catalog(args.customer_id, output, qdrant_url))


if __name__ == "__main__":
    main()
