from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from lets_go_video_agent.application.errors import UnsupportedMediaError

ALLOWED_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".webm"})


class LocalUploadStore:
    """开发态上传存储。

    文件名只用于保留扩展名，真实 object key 使用随机 UUID，避免路径穿越和重名覆盖。
    生产环境会把相同接口替换为 MinIO/S3。
    """

    def __init__(
        self,
        root: Path,
        max_bytes: int,
        *,
        object_key_prefix: str = "",
    ) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes
        self.object_key_prefix = object_key_prefix.strip("/")

    async def save(self, upload: UploadFile) -> tuple[str, int, str]:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in ALLOWED_VIDEO_SUFFIXES:
            raise UnsupportedMediaError(f"暂不支持 {suffix or '无扩展名'}；允许 MP4/MOV/MKV/WebM")

        original_stem = Path(upload.filename or "local-video").stem
        safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", original_stem).strip(" ._")
        safe_stem = safe_stem[:100] or "local-video"
        task_time = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        relative_key = (
            Path("understanding-tasks")
            / f"{task_time}_LOCAL_{safe_stem}"
            / f"{uuid4().hex}{suffix}"
        )
        destination = (self.root / relative_key).resolve()
        if self.root not in destination.parents:
            raise UnsupportedMediaError("非法上传路径")
        destination.parent.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256()
        size = 0
        try:
            with destination.open("xb") as file_handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise UnsupportedMediaError("视频文件超过配置的大小限制")
                    digest.update(chunk)
                    file_handle.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        key = relative_key.as_posix()
        if self.object_key_prefix:
            key = f"{self.object_key_prefix}/{key}"
        return key, size, digest.hexdigest()
