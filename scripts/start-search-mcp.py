"""幂等地后台启动 Search MCP，避开 PowerShell 环境变量大小写冲突。"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path


def port_is_open(host: str = "127.0.0.1", port: int = 8090) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.8):
            return True
    except OSError:
        return False


def main() -> int:
    if port_is_open():
        print("Search MCP process is already listening on 127.0.0.1:8090")
        return 0

    project_root = Path(__file__).resolve().parents[1]
    log_directory = project_root / "var" / "logs" / "search-mcp"
    log_directory.mkdir(parents=True, exist_ok=True)
    creation_flags = (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NO_WINDOW
    )
    with (
        (log_directory / "server.out.log").open("ab", buffering=0) as output,
        (log_directory / "server.err.log").open("ab", buffering=0) as error,
    ):
        process = subprocess.Popen(
            [sys.executable, "-m", "lets_go_video_agent.mcp.search_server"],
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=error,
            creationflags=creation_flags,
            close_fds=True,
        )
    print(f"Search MCP started in background, pid={process.pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
