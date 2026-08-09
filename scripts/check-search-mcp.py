"""对 Search MCP 做真实协议健康检查，供启动脚本和人工排障复用。"""

from __future__ import annotations

import asyncio
import os

from lets_go_video_agent.infrastructure.search.mcp_search_client import McpSearchClient


async def main() -> int:
    endpoint = os.getenv("SEARCH_MCP_URL", "http://127.0.0.1:8090/mcp")
    client = McpSearchClient(url=endpoint)
    return 0 if await client.health() else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
