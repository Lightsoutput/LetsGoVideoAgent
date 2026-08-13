from __future__ import annotations

import asyncio
import json
import re
import shutil
from collections.abc import Sequence
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from lets_go_video_agent.application.ports import AppStore, VideoRepository
from lets_go_video_agent.domain.skill import SkillProject
from lets_go_video_agent.domain.video import UploadSource, Video, VideoStatus
from lets_go_video_agent.media.local_storage import ALLOWED_VIDEO_SUFFIXES

LIBRARY_KEY_PREFIX = "library/"
_WINDOWS_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_BVID = re.compile(r"\b(BV[0-9A-Za-z]{10,})\b", re.IGNORECASE)


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


def video_library_relative_directory(video: Video, *, media_id: str | None = None) -> Path:
    """按业务用途生成可读且稳定的目录，不再暴露随机 UUID。"""

    bvid = _extract_bvid(video, media_id) or "LOCAL"
    title = _safe_component(video.title, fallback="未命名视频", limit=120)
    media_folder = _safe_component(f"{bvid}_{title}", fallback=str(video.id), limit=150)
    if video.metadata.get("library_scope") == "skill-project":
        project_name = _safe_component(
            str(video.metadata.get("skill_project_name") or "unassigned-project"),
            fallback="unassigned-project",
            limit=80,
        )
        project_id = str(video.metadata.get("skill_project_id") or video.id)[:8]
        return Path("skill-projects") / f"{project_id}_{project_name}" / media_folder
    task_time = video.created_at.strftime("%Y%m%d-%H%M%S")
    return Path("understanding-tasks") / f"{task_time}_{media_folder}"


async def organize_video_library(store: AppStore, library_dir: Path) -> list[dict[str, str]]:
    """安全迁移旧 UUID 目录并同步 object key；目标存在时绝不覆盖。"""

    root = await asyncio.to_thread(library_dir.resolve)
    changes: list[dict[str, str]] = []
    projects = {project.id: project for project in await store.list_skill_projects()}
    project_by_video: dict[object, SkillProject] = {}
    for project_id, project in projects.items():
        for item in await store.list_skill_project_items(project_id):
            if item.video_id:
                project_by_video[item.video_id] = project
    for video in await store.list():
        if video.source_object_key is None or not video.source_object_key.startswith(
            LIBRARY_KEY_PREFIX
        ):
            continue
        current_file = resolve_video_source(
            object_key=video.source_object_key,
            data_dir=root,
            library_dir=root,
        )
        if not current_file.is_file():
            continue
        if video.id in project_by_video:
            project = project_by_video[video.id]
            video.metadata.update(
                {
                    "library_scope": "skill-project",
                    "skill_project_id": str(project.id),
                    "skill_project_name": project.name,
                }
            )
        else:
            video.metadata.setdefault("library_scope", "understanding")
        relative_dir = video_library_relative_directory(video)
        current_dir = current_file.parent.resolve()
        target_dir = (root / relative_dir).resolve()
        if current_dir == target_dir:
            continue
        if root not in current_dir.parents or root not in target_dir.parents:
            continue
        if target_dir.exists():
            changes.append(
                {"status": "skipped", "source": str(current_dir), "target": str(target_dir)}
            )
            continue
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(current_dir), str(target_dir))
        target_file = target_dir / current_file.name
        video.source_object_key = library_object_key(target_file, root)
        video.metadata["library_relative_path"] = target_file.relative_to(root).as_posix()
        video.metadata["library_scope"] = (
            "skill-project" if video.id in project_by_video else "understanding"
        )
        _rewrite_download_manifest(target_dir, current_dir, target_dir, root)
        await store.update(video)
        changes.append({"status": "moved", "source": str(current_dir), "target": str(target_dir)})
    return changes


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


def _safe_component(value: str, *, fallback: str, limit: int) -> str:
    cleaned = _WINDOWS_ILLEGAL.sub("_", " ".join(value.split())).strip(" ._")
    return (cleaned[:limit].rstrip(" ._") or fallback)


def _extract_bvid(video: Video, media_id: str | None = None) -> str | None:
    candidates: Sequence[str] = (
        media_id or "",
        str(getattr(video.source, "original_url", "")),
        str(getattr(video.source, "canonical_url", "")),
        video.source_object_key or "",
    )
    for candidate in candidates:
        match = _BVID.search(candidate)
        if match:
            return match.group(1)
    return None


def _rewrite_download_manifest(
    directory: Path, old_directory: Path, new_directory: Path, root: Path
) -> None:
    manifest = directory / "download-complete.json"
    if not manifest.is_file():
        return
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        old_path = Path(str(payload.get("relative_path", "")))
        filename = old_path.name
        media_path = new_directory / filename
        if not media_path.is_file():
            return
        payload["relative_path"] = media_path.relative_to(root).as_posix()
        temporary = manifest.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(manifest)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return
