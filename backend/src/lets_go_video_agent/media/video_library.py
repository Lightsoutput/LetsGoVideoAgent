from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from lets_go_video_agent.application.ports import VideoRepository
from lets_go_video_agent.domain.video import UploadSource, Video, VideoStatus
from lets_go_video_agent.media.local_storage import ALLOWED_VIDEO_SUFFIXES

LIBRARY_KEY_PREFIX = "library/"


def library_object_key(path: Path, library_dir: Path) -> str:
    """将真实文件转换成可持久化的库内键，不把绝对路径写进领域对象。"""

    root = library_dir.resolve()
    resolved = path.resolve()
    if root not in resolved.parents:
        raise ValueError("视频文件不在项目视频库中")
    return f"{LIBRARY_KEY_PREFIX}{resolved.relative_to(root).as_posix()}"


def resolve_video_source(
    *,
    object_key: str,
    data_dir: Path,
    library_dir: Path,
) -> Path:
    """同时兼容旧 data/ 对象键与新的 videos/ 持久视频库键。"""

    if object_key.startswith(LIBRARY_KEY_PREFIX):
        root = library_dir.resolve()
        relative = object_key.removeprefix(LIBRARY_KEY_PREFIX)
    else:
        root = data_dir.resolve()
        relative = object_key
    target = (root / relative).resolve()
    if root not in target.parents:
        raise ValueError("视频来源路径越界")
    return target


async def sync_video_library(
    repository: VideoRepository,
    library_dir: Path,
) -> list[Video]:
    """扫描项目 videos/ 目录，把手动放入或已下载的视频幂等登记到视频库。"""

    root, files = await asyncio.to_thread(_discover_video_files, library_dir)
    existing = list(await repository.list())
    known_keys = {item.source_object_key for item in existing if item.source_object_key}
    registered: list[Video] = []
    for path, size_bytes in files:
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        object_key = library_object_key(path, root)
        if object_key in known_keys:
            continue
        stable_id = uuid5(
            NAMESPACE_URL,
            f"lets-go-video-agent:library:{relative.as_posix().casefold()}",
        )
        if await repository.get(stable_id) is not None:
            continue
        video = Video(
            id=stable_id,
            title=path.stem,
            source=UploadSource(
                original_filename=path.name,
                content_type=_media_type(path.suffix),
                size_bytes=size_bytes,
            ),
            source_object_key=object_key,
            status=VideoStatus.CREATED,
            current_stage="local_library_ready",
            metadata={
                "local_library": True,
                "library_relative_path": relative.as_posix(),
            },
        )
        await repository.add(video)
        registered.append(video)
        known_keys.add(object_key)
    return registered


def _discover_video_files(library_dir: Path) -> tuple[Path, list[tuple[Path, int]]]:
    root = library_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    files: list[tuple[Path, int]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in ALLOWED_VIDEO_SUFFIXES:
            files.append((path, path.stat().st_size))
    return root, files


def _media_type(suffix: str) -> str:
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }.get(suffix.lower(), "application/octet-stream")
