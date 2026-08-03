from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class ProcessExecutionError(RuntimeError):
    """外部媒体进程执行失败的基类。"""


class ProcessTimeoutError(ProcessExecutionError):
    """外部进程超过明确的执行时限。"""


class ProcessOutputTooLargeError(ProcessExecutionError):
    """外部进程输出异常膨胀，继续解析可能耗尽 Worker 内存。"""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class ProcessRunner(Protocol):
    async def __call__(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: float,
        max_output_bytes: int = 8 * 1024 * 1024,
    ) -> ProcessResult: ...


async def run_process(
    args: Sequence[str],
    *,
    timeout_seconds: float,
    max_output_bytes: int = 8 * 1024 * 1024,
) -> ProcessResult:
    """在不经过 Shell 的前提下运行一个有时限的外部命令。

    FFmpeg 与 yt-dlp 的参数可能包含来自任务的路径或 URL。参数数组配合
    ``shell=False`` 能保证这些值不会被解释为管道、重定向或另一条命令。
    此处是整个媒体层唯一允许启动子进程的边界，便于统一审计超时和输出上限。
    """

    command = tuple(str(part) for part in args)
    if not command or not command[0].strip():
        raise ValueError("外部命令不能为空")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")
    if max_output_bytes <= 0:
        raise ValueError("max_output_bytes 必须大于 0")

    def invoke() -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                shell=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProcessTimeoutError(
                f"外部命令在 {timeout_seconds:g} 秒后超时: {command[0]}"
            ) from exc

    completed = await asyncio.to_thread(invoke)
    output_size = len(completed.stdout) + len(completed.stderr)
    if output_size > max_output_bytes:
        raise ProcessOutputTooLargeError(
            f"外部命令输出 {output_size} 字节，超过 {max_output_bytes} 字节限制"
        )

    # 媒体工具在不同平台上的编码设置并不完全一致。使用替换策略保留可排障信息，
    # 同时避免一次非 UTF-8 日志让整个视频任务失败。
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    return ProcessResult(
        args=command,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
    )
