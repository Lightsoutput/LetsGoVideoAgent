from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel
from lets_go_video_agent.media.subprocesses import (
    ProcessRunner,
    ProcessTimeoutError,
    run_process,
)


class FFmpegError(RuntimeError):
    """FFmpeg/ffprobe 适配器错误。"""


class FFmpegTimeoutError(FFmpegError):
    """媒体命令超过配置时限。"""


class FFmpegCommandError(FFmpegError):
    """媒体命令返回非零状态或产生无效结果。"""


class VideoStreamInfo(DomainModel):
    codec: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)


class AudioStreamInfo(DomainModel):
    codec: str | None = None
    sample_rate: int | None = Field(default=None, gt=0)
    channels: int | None = Field(default=None, gt=0)


class MediaProbe(DomainModel):
    duration_ms: int = Field(gt=0)
    format_name: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    video: VideoStreamInfo | None = None
    audio: AudioStreamInfo | None = None


class FFmpegAdapter:
    """受目录约束的 FFmpeg/ffprobe 生产适配器。

    适配器只允许读写 ``media_root`` 内的文件。这样即使上层任务传入恶意路径，
    也不能让 Worker 读取系统文件或覆盖项目目录之外的内容。
    """

    def __init__(
        self,
        *,
        media_root: Path,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        command_timeout_seconds: float = 600,
        probe_timeout_seconds: float = 60,
        runner: ProcessRunner | None = None,
    ) -> None:
        self._root = media_root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._ffmpeg_binary = ffmpeg_binary
        self._ffprobe_binary = ffprobe_binary
        self._command_timeout_seconds = command_timeout_seconds
        self._probe_timeout_seconds = probe_timeout_seconds
        self._runner = runner or run_process

    async def probe(self, source: Path | str) -> MediaProbe:
        input_path = self._resolve_input(source)
        args = [
            self._ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            (
                "format=duration,format_name,size:"
                "stream=codec_type,codec_name,width,height,avg_frame_rate,"
                "sample_rate,channels"
            ),
            "-of",
            "json",
            str(input_path),
        ]
        result = await self._run(args, timeout_seconds=self._probe_timeout_seconds)
        try:
            payload = json.loads(result)
        except json.JSONDecodeError as exc:
            raise FFmpegCommandError("ffprobe 返回了无效 JSON") from exc
        if not isinstance(payload, Mapping):
            raise FFmpegCommandError("ffprobe JSON 顶层必须是对象")
        return self._parse_probe(payload)

    async def extract_audio(
        self,
        *,
        source: Path | str,
        destination: Path | str,
        sample_rate: int = 16_000,
        channels: int = 1,
    ) -> Path:
        if sample_rate < 8_000 or sample_rate > 192_000:
            raise ValueError("sample_rate 必须位于 8000 到 192000 之间")
        if channels not in {1, 2}:
            raise ValueError("P0 仅允许导出单声道或双声道音频")

        input_path = self._resolve_input(source)
        output_path = self._resolve_output(destination, {".wav"})
        if self._is_complete(output_path):
            return output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        args = [
            self._ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-n",
            "-i",
            str(input_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
            str(output_path),
        ]
        try:
            await self._run(args, timeout_seconds=self._command_timeout_seconds)
            self._require_nonempty_output(output_path)
        except Exception:
            # 只清理本次预期生成的目标；绝不对父目录做递归删除。
            output_path.unlink(missing_ok=True)
            raise
        return output_path

    async def capture_frame(
        self,
        *,
        source: Path | str,
        timestamp_ms: int,
        destination: Path | str,
        max_width: int | None = 1600,
    ) -> Path:
        if timestamp_ms < 0:
            raise ValueError("timestamp_ms 不能为负数")
        if max_width is not None and not 320 <= max_width <= 7680:
            raise ValueError("max_width 必须位于 320 到 7680 之间")

        input_path = self._resolve_input(source)
        output_path = self._resolve_output(destination, {".jpg", ".jpeg", ".png", ".webp"})
        if self._is_complete(output_path):
            return output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        args = [
            self._ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-n",
            "-i",
            str(input_path),
            "-ss",
            f"{timestamp_ms / 1000:.3f}",
            "-frames:v",
            "1",
        ]
        if max_width is not None:
            # -2 让 FFmpeg 自动计算偶数高度，避免部分编码器拒绝奇数尺寸。
            args.extend(["-vf", f"scale='min({max_width},iw)':-2"])
        args.extend(["-q:v", "2", str(output_path)])

        try:
            await self._run(args, timeout_seconds=self._command_timeout_seconds)
            self._require_nonempty_output(output_path)
        except Exception:
            output_path.unlink(missing_ok=True)
            raise
        return output_path

    async def _run(self, args: list[str], *, timeout_seconds: float) -> str:
        try:
            result = await self._runner(
                args,
                timeout_seconds=timeout_seconds,
                max_output_bytes=8 * 1024 * 1024,
            )
        except ProcessTimeoutError as exc:
            raise FFmpegTimeoutError(str(exc)) from exc
        if result.returncode != 0:
            # 日志只保留末尾，既能排障，也避免把超长媒体元数据写入 Trace。
            detail = result.stderr.strip()[-2_000:] or "无错误输出"
            raise FFmpegCommandError(f"{Path(args[0]).name} 执行失败: {detail}")
        return result.stdout

    def _resolve_input(self, value: Path | str) -> Path:
        path = self._resolve_inside_root(value)
        if not path.is_file():
            raise FileNotFoundError(f"媒体源不存在或不是文件: {path.name}")
        return path

    def _resolve_output(self, value: Path | str, allowed_suffixes: set[str]) -> Path:
        path = self._resolve_inside_root(value)
        if path.suffix.lower() not in allowed_suffixes:
            allowed = ", ".join(sorted(allowed_suffixes))
            raise ValueError(f"输出扩展名必须是: {allowed}")
        return path

    def _resolve_inside_root(self, value: Path | str) -> Path:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self._root / candidate
        resolved = candidate.resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise ValueError("媒体路径超出配置的数据目录")
        return resolved

    @staticmethod
    def _is_complete(path: Path) -> bool:
        # Temporal Activity 可能在成功后、回传结果前被重试。复用非空产物可以让
        # 转码与抽帧具备幂等语义，避免昂贵操作被重复执行。
        return path.is_file() and path.stat().st_size > 0

    @staticmethod
    def _require_nonempty_output(path: Path) -> None:
        if not path.is_file() or path.stat().st_size <= 0:
            raise FFmpegCommandError("FFmpeg 未生成有效输出文件")

    @staticmethod
    def _parse_probe(payload: Mapping[object, object]) -> MediaProbe:
        format_value = payload.get("format")
        format_data = format_value if isinstance(format_value, Mapping) else {}
        duration_raw = format_data.get("duration")
        try:
            duration_ms = round(float(str(duration_raw)) * 1000)
        except (TypeError, ValueError) as exc:
            raise FFmpegCommandError("ffprobe 未返回有效视频时长") from exc
        if duration_ms <= 0:
            raise FFmpegCommandError("视频时长必须大于 0")

        size_bytes: int | None = None
        size_raw = format_data.get("size")
        if size_raw is not None:
            try:
                size_bytes = int(str(size_raw))
            except ValueError:
                size_bytes = None

        video: VideoStreamInfo | None = None
        audio: AudioStreamInfo | None = None
        streams_value = payload.get("streams")
        streams = streams_value if isinstance(streams_value, list) else []
        for stream_value in streams:
            if not isinstance(stream_value, Mapping):
                continue
            codec_type = str(stream_value.get("codec_type", ""))
            if codec_type == "video" and video is None:
                video = VideoStreamInfo(
                    codec=_optional_string(stream_value.get("codec_name")),
                    width=_optional_positive_int(stream_value.get("width")),
                    height=_optional_positive_int(stream_value.get("height")),
                    fps=_parse_frame_rate(stream_value.get("avg_frame_rate")),
                )
            elif codec_type == "audio" and audio is None:
                audio = AudioStreamInfo(
                    codec=_optional_string(stream_value.get("codec_name")),
                    sample_rate=_optional_positive_int(stream_value.get("sample_rate")),
                    channels=_optional_positive_int(stream_value.get("channels")),
                )

        return MediaProbe(
            duration_ms=duration_ms,
            format_name=_optional_string(format_data.get("format_name")),
            size_bytes=size_bytes,
            video=video,
            audio=audio,
        )


def _optional_string(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_positive_int(value: object) -> int | None:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _parse_frame_rate(value: object) -> float | None:
    text = str(value or "")
    try:
        if "/" in text:
            numerator_text, denominator_text = text.split("/", maxsplit=1)
            denominator = float(denominator_text)
            if denominator == 0:
                return None
            result = float(numerator_text) / denominator
        else:
            result = float(text)
    except ValueError:
        return None
    return result if math.isfinite(result) and result > 0 else None
