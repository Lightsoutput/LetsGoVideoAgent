from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel, Provenance, TimeRange


class SemanticEvent(DomainModel):
    """经过多模态互证后形成的视频事件。

    TimelineArtifact 保存各条原始轨道；SemanticEvent 则回答“这一段发生了什么”。
    两者分开后，章节和问答可以使用高层语义，同时仍能回到原始证据审计。
    """

    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    time_range: TimeRange
    event_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=2_000)
    participants: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    causes: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    artifact_ids: list[UUID] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    provenance: Provenance


class NarrativeContext(DomainModel):
    """对整段视频的叙事理解，而不是字幕或 OCR 的简单摘要。"""

    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    video_format: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1, max_length=600)
    summary: str = Field(min_length=1, max_length=4_000)
    audience: str | None = Field(default=None, max_length=300)
    participants: list[str] = Field(default_factory=list)
    settings: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    event_ids: list[UUID] = Field(default_factory=list)
    artifact_ids: list[UUID] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    version: int = Field(default=1, ge=1)
    provenance: Provenance
