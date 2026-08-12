"""确保本地联网搜索栈可用，并输出可机器读取的分层诊断结果。

这段脚本只负责开发机上的生命周期管理：Docker Desktop -> SearXNG -> Search MCP。
业务代码仍然只通过 MCP 协议访问搜索能力，避免把 Docker 或 SearXNG 细节泄漏到 Agent。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from lets_go_video_agent.infrastructure.search.mcp_search_client import McpSearchClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MCP_URL = os.getenv("SEARCH_MCP_URL", "http://127.0.0.1:8090/mcp")
SEARXNG_URL = os.getenv("SEARCH_API_BASE", "http://127.0.0.1:8888")


@dataclass(slots=True)
class LayerStatus:
    """单层服务状态，前端和人工排障都可以直接消费。"""

    name: str
    status: str
    endpoint: str | None = None
    message: str = ""


def _port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _docker_ready() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _wait_until(check: object, timeout_seconds: int, interval: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if callable(check) and check():
            return True
        time.sleep(interval)
    return False


def _searxng_ready() -> bool:
    """检查 SearXNG 服务本身，不把外部搜索引擎限流误判为容器故障。"""
    try:
        with urllib.request.urlopen(f"{SEARXNG_URL}/healthz", timeout=4) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def _start_searxng() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--project-directory",
                str(PROJECT_ROOT),
                "up",
                "-d",
                "searxng",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    message = (result.stderr or result.stdout).strip()
    return result.returncode == 0, message[-500:]


def _start_mcp() -> tuple[bool, str]:
    if _port_open("127.0.0.1", 8090):
        return True, "Search MCP 已监听"
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "start-search-mcp.py")],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return False, str(exc)
    return result.returncode == 0, (result.stderr or result.stdout).strip()


async def _mcp_ready() -> bool:
    return await McpSearchClient(url=MCP_URL).health()


async def _real_search() -> bool:
    results = await McpSearchClient(url=MCP_URL).search(
        "明日方舟 攻略", limit=1, language="zh-CN"
    )
    return bool(results)


async def ensure(*, repair_services: bool, verify_search: bool) -> list[LayerStatus]:
    layers: list[LayerStatus] = []

    docker_ready = _docker_ready()
    layers.append(
        LayerStatus(
            name="docker_engine",
            status="ready" if docker_ready else "unavailable",
            message=(
                "Docker Engine 可用"
                if docker_ready
                else "Docker Desktop 未启动；请由用户手动启动，本项目不会自动拉起"
            ),
        )
    )
    if not docker_ready:
        return layers

    searx_ready = _searxng_ready()
    start_message = "SearXNG 已运行"
    if not searx_ready and repair_services:
        started, start_message = _start_searxng()
        searx_ready = started and _wait_until(_searxng_ready, timeout_seconds=60)
    layers.append(
        LayerStatus(
            name="searxng",
            status="ready" if searx_ready else "unavailable",
            endpoint=SEARXNG_URL,
            message="搜索引擎可用" if searx_ready else start_message,
        )
    )
    if not searx_ready:
        return layers

    mcp_ready = await _mcp_ready()
    mcp_message = "Search MCP 协议可用"
    if not mcp_ready and repair_services:
        started, mcp_message = _start_mcp()
        if started:
            for _ in range(20):
                if await _mcp_ready():
                    mcp_ready = True
                    break
                await asyncio.sleep(1)
    layers.append(
        LayerStatus(
            name="search_mcp",
            status="ready" if mcp_ready else "unavailable",
            endpoint=MCP_URL,
            message="MCP 协议与下游搜索均可用" if mcp_ready else mcp_message,
        )
    )

    if mcp_ready and verify_search:
        search_ready = await _real_search()
        layers.append(
            LayerStatus(
                name="real_search",
                status="ready" if search_ready else "unavailable",
                message="真实检索返回结果" if search_ready else "协议可用，但真实检索没有结果",
            )
        )
    return layers


def _payload(layers: list[LayerStatus]) -> dict[str, object]:
    status = "ready" if layers and all(item.status == "ready" for item in layers) else "unavailable"
    return {"status": status, "layers": [asdict(item) for item in layers]}


def main() -> int:
    parser = argparse.ArgumentParser(description="启动并检查联网搜索栈")
    parser.add_argument("--check-only", action="store_true", help="只检查，不启动 SearXNG 或 MCP")
    parser.add_argument("--skip-real-search", action="store_true", help="跳过真实检索冒烟测试")
    args = parser.parse_args()
    layers = asyncio.run(
        ensure(repair_services=not args.check_only, verify_search=not args.skip_real_search)
    )
    payload = _payload(layers)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
