from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import Field, HttpUrl

from lets_go_video_agent.domain.common import DomainModel, utc_now


class UploadSource(DomainModel):
    kind: Literal["upload"] = "upload"
    original_filename: str
    content_type: str
    size_bytes: int = Field(ge=0)
    sha256: str | None = None


class WebSource(DomainModel):
    kind: Literal["web"] = "web"
    original_url: HttpUrl
    canonical_url: HttpUrl | None = None
    extractor: str | None = None
    rights_confirmed: bool = False


class SyntheticSource(DomainModel):
    kind: Literal["synthetic"] = "synthetic"
    fixture_name: str


VideoSource = Annotated[UploadSource | WebSource | SyntheticSource, Field(discriminator="kind")]


class VideoStatus(str):
    """字符串常量而非数据库枚举，便于后续新增可恢复状态。"""

    CREATED = "created"
    IMPORTING = "importing"
    VALIDATING = "validating"
    PROCESSING = "processing"
    PARTIALLY_READY = "partially_ready"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Video(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=300)
    source: VideoSource
    status: str = VideoStatus.CREATED
    duration_ms: int | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)
    source_object_key: str | None = None
    progress: float = Field(default=0, ge=0, le=1)
    current_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
