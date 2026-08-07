from __future__ import annotations

import httpx


class SearxngClient:
    """免费自建 SearXNG 搜索适配器；不可用时返回空结果，不拖垮媒体 Worker。"""

    def __init__(self, *, api_base: str, timeout_seconds: float = 8) -> None:
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout_seconds

    async def search(
        self, query: str, *, limit: int = 5, language: str = "zh-CN"
    ) -> list[dict[str, str]]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._api_base}/search",
                    params={"q": query, "format": "json", "language": language},
                )
            response.raise_for_status()
            results = response.json().get("results", [])
        except (httpx.HTTPError, ValueError, TypeError):
            return []
        return [
            {
                "title": str(item.get("title", ""))[:200],
                "url": str(item.get("url", ""))[:2_000],
                "content": str(item.get("content", ""))[:600],
            }
            for item in results[:limit]
            if isinstance(item, dict) and item.get("url")
        ]
