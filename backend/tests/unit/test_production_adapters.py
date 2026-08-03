from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from lets_go_video_agent.infrastructure.cache.redis import RedisCache
from lets_go_video_agent.infrastructure.models.litellm_gateway import (
    ChatMessage,
    LiteLLMModelGateway,
)
from lets_go_video_agent.infrastructure.objects.s3 import S3ObjectStore
from lets_go_video_agent.infrastructure.vectors.qdrant import VectorPoint
from lets_go_video_agent.media.ffmpeg import FFmpegAdapter
from lets_go_video_agent.media.subprocesses import ProcessResult
from lets_go_video_agent.media.ytdlp import RemoteDownloadDisabledError, YtDlpAdapter
from lets_go_video_agent.workflows.video_processing import VideoProcessingWorkflow
from lets_go_video_agent.workflows.worker import run as run_temporal_worker


@pytest.mark.asyncio
async def test_ffprobe_adapter_parses_typed_metadata_without_shell(tmp_path: Path) -> None:
    source = tmp_path / "fixture.mp4"
    await asyncio.to_thread(source.write_bytes, b"synthetic-media-placeholder")
    captured: list[tuple[str, ...]] = []

    async def fake_runner(
        args: Sequence[str],
        *,
        timeout_seconds: float,
        max_output_bytes: int = 8 * 1024 * 1024,
    ) -> ProcessResult:
        del timeout_seconds, max_output_bytes
        captured.append(tuple(args))
        return ProcessResult(
            args=tuple(args),
            returncode=0,
            stdout=(
                '{"format":{"duration":"2.5","format_name":"mp4","size":"24"},'
                '"streams":[{"codec_type":"video","codec_name":"h264",'
                '"width":1280,"height":720,"avg_frame_rate":"30/1"}]}'
            ),
            stderr="",
        )

    probe = await FFmpegAdapter(media_root=tmp_path, runner=fake_runner).probe(source)

    assert probe.duration_ms == 2_500
    assert probe.video is not None and probe.video.fps == 30
    assert captured and captured[0][0] == "ffprobe"
    assert all(token not in {"cmd", "powershell", "sh"} for token in captured[0])


@pytest.mark.asyncio
async def test_ytdlp_is_disabled_before_any_network_or_process_call(tmp_path: Path) -> None:
    adapter = YtDlpAdapter(
        download_root=tmp_path,
        remote_enabled=False,
        max_download_bytes=1_024,
    )

    with pytest.raises(RemoteDownloadDisabledError):
        await adapter.inspect("https://www.bilibili.com/video/BV1example/")


@pytest.mark.asyncio
async def test_ytdlp_download_uses_browser_compatible_single_video_format(tmp_path: Path) -> None:
    captured: list[tuple[str, ...]] = []

    async def fake_runner(
        args: Sequence[str],
        *,
        timeout_seconds: float,
        max_output_bytes: int = 8 * 1024 * 1024,
    ) -> ProcessResult:
        del timeout_seconds, max_output_bytes
        captured.append(tuple(args))
        template = Path(args[args.index("-o") + 1])
        media_path = template.parent / "BV1fixture.mp4"
        media_path.write_bytes(b"fixture-media")
        return ProcessResult(tuple(args), 0, f"{media_path}\n", "")

    async def public_dns(_hostname: str, _port: int) -> Sequence[str]:
        return ["8.8.8.8"]

    adapter = YtDlpAdapter(
        download_root=tmp_path,
        remote_enabled=True,
        max_download_bytes=1_024,
        cookies_from_browser="edge",
        ffmpeg_location="C:/tools/ffmpeg.exe",
        runner=fake_runner,
        dns_resolver=public_dns,
    )
    result = await adapter.download(
        url="https://www.bilibili.com/video/BV1fixture/",
        idempotency_key="job-1",
        rights_confirmed=True,
    )

    command = captured[0]
    assert result.path.name == "BV1fixture.mp4"
    assert "--no-playlist" in command
    assert "--max-downloads" not in command
    assert "--cookies-from-browser" in command
    assert "--ffmpeg-location" in command
    assert "vcodec^=avc" in command[command.index("--format") + 1]


@pytest.mark.asyncio
async def test_s3_rejects_path_traversal_before_calling_client() -> None:
    store = S3ObjectStore(bucket="fixture", client=object())

    with pytest.raises(ValueError, match="object key"):
        await store.put_bytes(key="../escape.mp4", data=b"fixture")


class _FakeRedisClient:
    def __init__(self) -> None:
        self.eval_args: tuple[object, ...] | None = None

    async def set(self, *_args: object, **_kwargs: object) -> bool:
        return True

    async def eval(self, *args: object) -> int:
        self.eval_args = args
        return 1


@pytest.mark.asyncio
async def test_redis_lease_uses_atomic_token_checked_release() -> None:
    client = _FakeRedisClient()
    cache = RedisCache(url="redis://unused", client=client)
    lease = cache.lease("video:fixture", ttl_seconds=30)

    assert await lease.acquire()
    await lease.release()

    assert client.eval_args is not None
    assert client.eval_args[1] == 1
    assert "lease:video:fixture" in str(client.eval_args[2])


@pytest.mark.asyncio
async def test_litellm_gateway_normalizes_usage_and_actual_cost() -> None:
    async def fake_completion(**_kwargs: object) -> object:
        return {
            "id": "response-1",
            "model": "economy/mock",
            "choices": [
                {
                    "message": {"content": "基于证据的回答"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        }

    gateway = LiteLLMModelGateway(
        default_model="economy/mock",
        allowed_models=frozenset({"economy/mock"}),
        completion=fake_completion,
        cost_calculator=lambda _response: Decimal("0.0012"),
    )
    result = await gateway.complete(
        messages=[ChatMessage(role="user", content="请总结这一段")],
        max_cost_usd=Decimal("0.01"),
    )

    assert result.content == "基于证据的回答"
    assert result.usage.total_tokens == 150
    assert result.usage.estimated_cost_usd == Decimal("0.0012")


def test_qdrant_vector_contract_rejects_non_finite_values() -> None:
    with pytest.raises(ValidationError):
        VectorPoint(
            id=uuid4(),
            video_id=uuid4(),
            embedding=[0.1, float("nan")],
            text="fixture",
            kind="transcript",
            time_range={"start_ms": 0, "end_ms": 1_000},  # type: ignore[arg-type]
        )


def test_temporal_worker_console_entrypoint_is_importable() -> None:
    assert callable(run_temporal_worker)
    assert VideoProcessingWorkflow.__name__ == "VideoProcessingWorkflow"
