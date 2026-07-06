#!/usr/bin/env python
"""Dump the gateway's tool names, either offline or from a running server.

Usage:
    # Offline (builds the gateway in-process, no network):
    uv run python scripts/dump_tools.py --out baseline_tools.txt

    # Against a running SSE server:
    uv run python scripts/dump_tools.py --url http://localhost:8001/sse/ --out live_tools.txt

Compare against the frozen baseline with:
    diff baseline_tools.txt live_tools.txt
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def dump_offline() -> list[str]:
    from gateway.app import build_gateway

    gateway = build_gateway()
    tools = await gateway.get_tools()
    return sorted(tools.keys())


async def dump_remote(url: str) -> list[str]:
    from fastmcp import Client

    async with Client(url) as client:
        tools = await client.list_tools()
    return sorted(t.name for t in tools)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump MCP gateway tool names")
    parser.add_argument("--url", help="SSE URL of a running server (omit for offline build)")
    parser.add_argument("--out", default="tools_dump.txt", help="Output file (default: tools_dump.txt)")
    args = parser.parse_args()

    if args.url:
        names = asyncio.run(dump_remote(args.url))
    else:
        names = asyncio.run(dump_offline())

    out = Path(args.out)
    out.write_text("\n".join(names) + "\n", encoding="utf-8")
    print(f"{len(names)} tools written to {out}")


if __name__ == "__main__":
    main()
