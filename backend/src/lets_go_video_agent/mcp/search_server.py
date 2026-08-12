from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from lets_go_video_agent.config import get_settings
from lets_go_video_agent.infrastructure.search.searxng_client import SearxngClient

settings = get_settings()
client = SearxngClient(api_base=settings.search_api_base)
mcp = FastMCP(
    "LetsGoVideoAgent Search MCP",
    instructions=(
        "通过本地 SearXNG 检索公开网页。视频 Agent 应只搜索低置信度专有名词、"
        "版本号和需要外部核验的事实，并保留来源 URL；搜索结果不能覆盖视频直接证据。"
    ),
    host=settings.search_mcp_host,
    port=settings.search_mcp_port,
)


@mcp.tool()
async def search_web(
    query: str, max_results: int = 5, language: str = "zh-CN"
) -> list[dict[str, str]]:
    """搜索公开网页，返回标题、URL 和摘要。"""
    bounded_limit = max(1, min(10, max_results))
    return await client.search(query, limit=bounded_limit, language=language)


@mcp.tool()
async def verify_terms(
    terms: list[str], context: str = "", max_results_per_term: int = 3
) -> dict[str, list[dict[str, str]]]:
    """并行核验一组疑似错字或专业名词，供字幕审核 Agent 做交叉验证。"""
    normalized = list(dict.fromkeys(term.strip() for term in terms if 1 < len(term.strip()) <= 60))[
        :10
    ]
    batches = await asyncio.gather(
        *(
            client.search(
                f"{context[:120]} {term}".strip(),
                limit=max(1, min(5, max_results_per_term)),
            )
            for term in normalized
        )
    )
    return dict(zip(normalized, batches, strict=True))


@mcp.tool()
async def search_health() -> dict[str, Any]:
    """检查 MCP 与其下游 SearXNG 是否可用。"""
    # 健康状态只判断 SearXNG HTTP 接口能否正确响应，不能用“是否搜到结果”判断。
    # 搜索结果为空并不等于服务故障，反过来 MCP 进程在线也不代表下游可用。
    searxng_ready = await client.health()
    return {
        "mcp": "ready",
        "searxng": "ready" if searxng_ready else "unavailable",
        "endpoint": settings.search_api_base,
    }


def run() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    run()
