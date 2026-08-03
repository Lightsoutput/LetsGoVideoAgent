from __future__ import annotations

import hashlib
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

    def __init__(self, root: Path, max_bytes: int) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes

    async def save(self, upload: UploadFile) -> tuple[str, int, str]:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in ALLOWED_VIDEO_SUFFIXES:
            raise UnsupportedMediaError(f"暂不支持 {suffix or '无扩展名'}；允许 MP4/MOV/MKV/WebM")

        relative_key = Path("uploads") / f"{uuid4().hex}{suffix}"
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
        return relative_key.as_posix(), size, digest.hexdigest()
