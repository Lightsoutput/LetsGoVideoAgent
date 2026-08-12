from __future__ import annotations

import httpx
from pytest import MonkeyPatch

from lets_go_video_agent.infrastructure.search import searxng_client as searxng_module
from lets_go_video_agent.infrastructure.search.searxng_client import SearxngClient


async def test_searxng_health_uses_service_health_endpoint(monkeypatch: MonkeyPatch) -> None:
    """外部引擎限流不能影响 SearXNG 容器自身的健康判断。"""
    requested_paths: list[str] = []
    original_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        return httpx.Response(200, text="OK")

    def build_client(*, timeout: float) -> httpx.AsyncClient:
        return original_async_client(
            timeout=timeout,
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(searxng_module.httpx, "AsyncClient", build_client)

    client = SearxngClient(api_base="http://127.0.0.1:8888")

    assert await client.health() is True
    assert requested_paths == ["/healthz"]
