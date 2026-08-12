from __future__ import annotations

from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class McpSearchClient:
    """通过 Streamable HTTP MCP 调用搜索工具，业务层不感知 SearXNG 实现。"""

    def __init__(self, *, url: str) -> None:
        self._url = url

    async def health(self) -> bool:
        """通过 MCP 工具检查服务与下游 SearXNG，不绕过协议直连内部地址。"""
        try:
            async with streamable_http_client(self._url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("search_health", arguments={})
        except Exception:
            return False
        structured = result.structuredContent
        if not isinstance(structured, dict):
            return False
        payload: Any = structured.get("result", structured)
        return (
            isinstance(payload, dict)
            and payload.get("mcp") == "ready"
            and payload.get("searxng") == "ready"
        )

    async def search(
        self, query: str, *, limit: int = 5, language: str = "zh-CN"
    ) -> list[dict[str, str]]:
        try:
            async with streamable_http_client(self._url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "search_web",
                        arguments={
                            "query": query,
                            "max_results": limit,
                            "language": language,
                        },
                    )
        except Exception:
            # 搜索是增强能力；MCP/SearXNG 不可用时不阻塞视频主处理。
            return []
        structured = result.structuredContent
        if not isinstance(structured, dict):
            return []
        values: Any = structured.get("result", structured.get("results", []))
        if not isinstance(values, list):
            return []
        return [
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "content": str(item.get("content", "")),
            }
            for item in values
            if isinstance(item, dict) and item.get("url")
        ]
