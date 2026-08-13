from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel
from lets_go_video_agent.media.subprocesses import (
    ProcessRunner,
    ProcessTimeoutError,
    run_process,
)
from lets_go_video_agent.media.url_policy import SourceUrlPolicy

DnsResolver = Callable[[str, int], Awaitable[Sequence[str]]]
_SAFE_IDEMPOTENCY_PART = re.compile(r'^[^<>:"|?*\x00-\x1f]{1,160}$')


class YtDlpError(RuntimeError):
    """yt-dlp 适配器错误。"""


class RemoteDownloadDisabledError(YtDlpError):
    pass


class MediaRightsNotConfirmedError(YtDlpError):
    pass


class YtDlpTimeoutError(YtDlpError):
    pass


class DownloadedMedia(DomainModel):
    path: Path
    size_bytes: int = Field(gt=0)
    sha256: str
    extractor: str | None = None
    canonical_url: str
    reused: bool = False


class YtDlpMetadata(DomainModel):
    media_id: str
    title: str
    duration_ms: int | None = Field(default=None, gt=0)
    extractor: str | None = None
    uploader: str | None = None
    canonical_url: str
    webpage_url: str
    thumbnail_url: str | None = None
    estimated_size_bytes: int | None = Field(default=None, gt=0)


class YtDlpAdapter:
    """网页视频元数据与授权下载适配器。

    初始 URL 会经过协议、主机和 DNS 公网地址检查；部署时仍应配合容器网络出口
    白名单，因为独立的 yt-dlp 进程内部重定向无法由应用层逐跳复核。
    """

    def __init__(
        self,
        *,
        download_root: Path,
        remote_enabled: bool,
        max_download_bytes: int,
        command_timeout_seconds: float = 1_800,
        metadata_timeout_seconds: float = 60,
        python_executable: str = sys.executable,
        cookies_from_browser: str | None = None,
        proxy_url: str | None = None,
        ffmpeg_location: str | None = None,
        url_policy: SourceUrlPolicy | None = None,
        runner: ProcessRunner | None = None,
        dns_resolver: DnsResolver | None = None,
    ) -> None:
        if max_download_bytes <= 0:
            raise ValueError("max_download_bytes 必须大于 0")
        self._root = download_root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._remote_enabled = remote_enabled
        self._max_download_bytes = max_download_bytes
        self._command_timeout_seconds = command_timeout_seconds
        self._metadata_timeout_seconds = metadata_timeout_seconds
        self._python_executable = python_executable
        self._cookies_from_browser = cookies_from_browser
        self._proxy_url = proxy_url
        self._ffmpeg_location = ffmpeg_location or _bundled_ffmpeg_location()
        self._url_policy = url_policy or SourceUrlPolicy()
        self._runner = runner or run_process
        self._dns_resolver = dns_resolver or _resolve_host_addresses

    async def inspect(self, url: str) -> YtDlpMetadata:
        safe_url = await self._validate_remote_url(url)
        args = [
            self._python_executable,
            "-X",
            "utf8",
            "-m",
            "yt_dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
            *self._authentication_args(),
            *self._network_args(),
            "--",
            safe_url,
        ]
        stdout = await self._execute(args, timeout_seconds=self._metadata_timeout_seconds)
        try:
            raw = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise YtDlpError("yt-dlp 返回了无效元数据 JSON") from exc
        if not isinstance(raw, Mapping):
            raise YtDlpError("yt-dlp 元数据顶层必须是对象")
        return _parse_metadata(raw, fallback_url=safe_url)

    async def download(
        self,
        *,
        url: str,
        idempotency_key: str,
        rights_confirmed: bool,
    ) -> DownloadedMedia:
        if not rights_confirmed:
            raise MediaRightsNotConfirmedError("下载视频前必须确认拥有相应使用权")
        safe_url = await self._validate_remote_url(url)
        key_parts = Path(idempotency_key.replace("\\", "/")).parts
        if (
            not key_parts
            or len(key_parts) > 6
            or any(
                part in {"", ".", ".."} or not _SAFE_IDEMPOTENCY_PART.fullmatch(part)
                for part in key_parts
            )
        ):
            raise ValueError("幂等目录必须是库内安全相对路径，且不能包含 Windows 非法字符")

        job_dir = self._resolve_inside_root(idempotency_key)
        job_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = job_dir / "download-complete.json"
        url_fingerprint = hashlib.sha256(safe_url.encode("utf-8")).hexdigest()
        existing = await asyncio.to_thread(
            self._read_completed_download,
            manifest_path,
            url_fingerprint,
        )
        if existing is not None:
            return existing.model_copy(update={"reused": True})
        reusable = await asyncio.to_thread(
            self._find_reusable_download,
            url_fingerprint,
            manifest_path,
        )
        if reusable is not None:
            return reusable.model_copy(update={"reused": True})

        output_template = job_dir / "%(id)s.%(ext)s"
        args = [
            self._python_executable,
            "-X",
            "utf8",
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--no-warnings",
            "--restrict-filenames",
            "--format",
            "bestvideo[vcodec^=avc]+bestaudio/best[vcodec^=avc]/best[ext=mp4]/best",
            "--max-filesize",
            str(self._max_download_bytes),
            "--merge-output-format",
            "mp4",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "zh-CN,zh-Hans,zh-Hant,zh.*",
            "--sub-format",
            "vtt/srt/best",
            *self._ffmpeg_args(),
            *self._authentication_args(),
            *self._network_args(),
            "--print",
            "after_move:filepath",
            "-o",
            str(output_template),
            "--",
            safe_url,
        ]
        stdout = await self._execute(args, timeout_seconds=self._command_timeout_seconds)
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        if not lines:
            raise YtDlpError("yt-dlp 未报告下载文件路径")

        media_path = self._resolve_inside_root(lines[-1])
        if not media_path.is_file() or media_path.stat().st_size <= 0:
            raise YtDlpError("yt-dlp 未生成有效媒体文件")
        size_bytes = media_path.stat().st_size
        if size_bytes > self._max_download_bytes:
            media_path.unlink(missing_ok=True)
            raise YtDlpError("下载结果超过配置的文件大小上限")

        digest = await asyncio.to_thread(_sha256_file, media_path)
        result = DownloadedMedia(
            path=media_path,
            size_bytes=size_bytes,
            sha256=digest,
            canonical_url=_redact_url(safe_url),
        )
        await asyncio.to_thread(
            self._write_manifest,
            manifest_path,
            result,
            url_fingerprint,
        )
        return result

    async def _validate_remote_url(self, url: str) -> str:
        if not self._remote_enabled:
            raise RemoteDownloadDisabledError("当前环境未启用远程媒体访问")
        safe_url = self._url_policy.validate(url)
        parts = urlsplit(safe_url)
        hostname = parts.hostname
        if hostname is None:
            raise YtDlpError("来源 URL 缺少主机名")
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        addresses = await self._dns_resolver(hostname, port)
        if not addresses:
            raise YtDlpError("来源主机没有可用 DNS 地址")
        for raw_address in addresses:
            try:
                address = ipaddress.ip_address(raw_address)
            except ValueError as exc:
                raise YtDlpError("DNS 解析器返回了无效 IP 地址") from exc
            if not address.is_global:
                raise YtDlpError("来源域名解析到私网、回环或保留地址")
        return safe_url

    async def _execute(self, args: list[str], *, timeout_seconds: float) -> str:
        try:
            result = await self._runner(
                args,
                timeout_seconds=timeout_seconds,
                max_output_bytes=8 * 1024 * 1024,
            )
        except ProcessTimeoutError as exc:
            raise YtDlpTimeoutError(str(exc)) from exc
        if result.returncode != 0:
            detail = result.stderr.strip()[-2_000:] or "无错误输出"
            raise YtDlpError(f"yt-dlp 执行失败: {detail}")
        return result.stdout

    def _authentication_args(self) -> list[str]:
        """按需读取本机浏览器 Cookie；默认不接触用户浏览器数据。"""
        if not self._cookies_from_browser:
            return []
        return ["--cookies-from-browser", self._cookies_from_browser]

    def _ffmpeg_args(self) -> list[str]:
        if not self._ffmpeg_location:
            return []
        return ["--ffmpeg-location", self._ffmpeg_location]

    def _network_args(self) -> list[str]:
        """网页下载与模型调用共用统一出站代理，避免只修通其中一条链路。"""

        return ["--proxy", self._proxy_url] if self._proxy_url else []

    def _resolve_inside_root(self, value: Path | str) -> Path:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self._root / candidate
        resolved = candidate.resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise YtDlpError("下载路径超出配置的数据目录")
        return resolved

    def _read_completed_download(
        self,
        manifest_path: Path,
        expected_url_fingerprint: str,
    ) -> DownloadedMedia | None:
        if not manifest_path.is_file():
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                return None
            if payload.get("url_fingerprint") != expected_url_fingerprint:
                raise YtDlpError("同一幂等键不能用于不同来源 URL")
            path_value = payload.get("relative_path")
            if not isinstance(path_value, str):
                return None
            path = self._resolve_inside_root(path_value)
            result = DownloadedMedia(
                path=path,
                size_bytes=int(str(payload.get("size_bytes"))),
                sha256=str(payload.get("sha256")),
                extractor=_optional_text(payload.get("extractor")),
                canonical_url=str(payload.get("canonical_url")),
                reused=True,
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if not result.path.is_file() or result.path.stat().st_size != result.size_bytes:
            return None
        return result

    def _find_reusable_download(
        self, expected_url_fingerprint: str, current_manifest: Path
    ) -> DownloadedMedia | None:
        """相同 URL 已下载时跨任务复用媒体，避免重试或重启后重复消耗带宽。"""
        for manifest in self._root.rglob("download-complete.json"):
            if manifest == current_manifest:
                continue
            try:
                result = self._read_completed_download(manifest, expected_url_fingerprint)
            except YtDlpError:
                continue
            if result is not None:
                return result
        return None

    def _write_manifest(
        self,
        manifest_path: Path,
        result: DownloadedMedia,
        url_fingerprint: str,
    ) -> None:
        # 先写临时文件再原子替换，避免 Worker 崩溃时留下“半份成功标记”。
        temporary_path = manifest_path.with_suffix(".tmp")
        relative_path = result.path.relative_to(self._root).as_posix()
        payload = {
            "url_fingerprint": url_fingerprint,
            "relative_path": relative_path,
            "size_bytes": result.size_bytes,
            "sha256": result.sha256,
            "extractor": result.extractor,
            "canonical_url": result.canonical_url,
        }
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        temporary_path.replace(manifest_path)


async def _resolve_host_addresses(hostname: str, port: int) -> Sequence[str]:
    def resolve() -> Sequence[str]:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        return sorted({str(record[4][0]) for record in records})

    return await asyncio.to_thread(resolve)


def _parse_metadata(raw: Mapping[object, object], *, fallback_url: str) -> YtDlpMetadata:
    media_id = _required_text(raw.get("id"), "id")
    title = _required_text(raw.get("title"), "title")
    duration_ms: int | None = None
    duration = raw.get("duration")
    if duration is not None:
        try:
            parsed_duration = round(float(str(duration)) * 1000)
        except ValueError:
            parsed_duration = 0
        if parsed_duration > 0:
            duration_ms = parsed_duration

    webpage_url = _redact_url(str(raw.get("webpage_url") or fallback_url))
    canonical_url = _redact_url(str(raw.get("original_url") or webpage_url))
    thumbnail = _optional_text(raw.get("thumbnail"))
    estimated_size_bytes: int | None = None
    size = raw.get("filesize") or raw.get("filesize_approx")
    if size is not None:
        try:
            parsed_size = int(str(size))
        except ValueError:
            parsed_size = 0
        if parsed_size > 0:
            estimated_size_bytes = parsed_size
    return YtDlpMetadata(
        media_id=media_id,
        title=title,
        duration_ms=duration_ms,
        extractor=_optional_text(raw.get("extractor_key") or raw.get("extractor")),
        uploader=_optional_text(raw.get("uploader")),
        canonical_url=canonical_url,
        webpage_url=webpage_url,
        thumbnail_url=_redact_url(thumbnail) if thumbnail else None,
        estimated_size_bytes=estimated_size_bytes,
    )


def _required_text(value: object, field_name: str) -> str:
    result = _optional_text(value)
    if result is None:
        raise YtDlpError(f"yt-dlp 元数据缺少字段: {field_name}")
    return result


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _redact_url(url: str) -> str:
    parts = urlsplit(url)
    # 查询串可能携带临时签名或登录令牌，领域对象与 Trace 只保留无凭据地址。
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundled_ffmpeg_location() -> str | None:
    """优先使用项目依赖自带的 FFmpeg，避免要求开发机全局配置 PATH。"""
    try:
        import imageio_ffmpeg  # type: ignore[import-untyped]
    except ImportError:
        return None
    return str(imageio_ffmpeg.get_ffmpeg_exe())
