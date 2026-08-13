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


class AgentTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ProcessingAgentTask(DomainModel):
    """一个 Agent 在单条视频上的公开工作快照，不包含隐藏思维链。"""

    agent_id: str
    agent_number: str
    display_name: str
    role: str
    status: AgentTaskStatus = AgentTaskStatus.PENDING
    phase: str = "等待"
    task: str = "等待上游任务"
    message: str = "尚未开始"
    progress: float = Field(default=0, ge=0, le=1)
    completed_units: int = Field(default=0, ge=0)
    total_units: int | None = Field(default=None, ge=0)
    model_provider: str | None = None
    model: str | None = None
    parallel_group: str | None = None
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


class ProcessingRun(DomainModel):
    """可轮询的媒体处理状态；前端不再只能看到一句“请等待”。"""

    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    trace_id: UUID = Field(default_factory=uuid4)
    status: ProcessingStatus = ProcessingStatus.QUEUED
    stage: str = "queued"
    stage_label: str = "等待处理"
    progress: float = Field(default=0, ge=0, le=1)
    elapsed_seconds: float = Field(default=0, ge=0)
    eta_seconds: float | None = Field(default=None, ge=0)
    message: str = "任务已进入队列"
    error: str | None = None
    attempt_count: int = Field(default=0, ge=0)
    agent_tasks: list[ProcessingAgentTask] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
