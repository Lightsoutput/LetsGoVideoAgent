from __future__ import annotations

from pathlib import Path

from temporalio import activity

from lets_go_video_agent.config import Settings
from lets_go_video_agent.media.ffmpeg import FFmpegAdapter
from lets_go_video_agent.workflows.contracts import ProcessingRequest


class VideoProcessingActivities:
    """Worker 中的确定性媒体 Activity。

    Agent 不直接执行 FFmpeg；Temporal 负责重试与恢复，适配器负责
    路径边界和子进程超时。目标文件已存在时 FFmpegAdapter 会复用，
    因此 Activity 在重试时不会重复转码。
    """

    def __init__(self, settings: Settings) -> None:
        self._media_root = settings.local_data_dir.resolve()
        self._ffmpeg = FFmpegAdapter(media_root=self._media_root)

    @activity.defn(name="probe_media")
    async def probe_media(self, request: ProcessingRequest) -> dict[str, object]:
        activity.heartbeat("probing")
        probe = await self._ffmpeg.probe(request.source_object_key)
        return probe.model_dump(mode="json")

    @activity.defn(name="extract_audio")
    async def extract_audio(self, request: ProcessingRequest) -> str:
        activity.heartbeat("extracting-audio")
        destination = Path("derived") / request.video_id / "audio-16k-mono.wav"
        result = await self._ffmpeg.extract_audio(
            source=request.source_object_key,
            destination=destination,
        )
        return result.relative_to(self._media_root).as_posix()
