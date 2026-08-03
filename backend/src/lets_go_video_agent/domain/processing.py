from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel, utc_now


class ProcessingStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingRun(DomainModel):
    """可轮询的媒体处理状态；前端不再只能看到一句“请等待”。"""

    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    status: ProcessingStatus = ProcessingStatus.QUEUED
    stage: str = "queued"
    stage_label: str = "等待处理"
    progress: float = Field(default=0, ge=0, le=1)
    elapsed_seconds: float = Field(default=0, ge=0)
    eta_seconds: float | None = Field(default=None, ge=0)
    message: str = "任务已进入队列"
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
