from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from lets_go_video_agent.domain.common import (
    DomainModel,
    Provenance,
    SpatialRegion,
    TimeRange,
)


class TimelineKind(StrEnum):
    CHAPTER = "chapter"
    SEGMENT = "segment"
    TRANSCRIPT = "transcript"
    SPEAKER_TURN = "speaker_turn"
    OCR = "ocr"
    VISUAL = "visual"
    EVENT = "event"
    SHOT = "shot"
    KEYFRAME = "keyframe"


class ObservationType(StrEnum):
    DIRECT = "direct"
    INFERENCE = "inference"
    USER_ANNOTATION = "user_annotation"


class TimelineArtifact(DomainModel):
    """多轨时间轴上的最小知识单元。

    字幕、OCR、镜头、视觉描述可以在时间上重叠，因此这里不强迫它们合并为一棵
    唯一章节树。章节只是其中一条高层语义轨道。
    """

    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    kind: TimelineKind
    time_range: TimeRange
    title: str | None = None
    text: str
    speaker: str | None = None
    confidence: float = Field(default=1, ge=0, le=1)
    observation_type: ObservationType = ObservationType.DIRECT
    spatial_region: SpatialRegion | None = None
    snapshot_key: str | None = None
    tags: list[str] = Field(default_factory=list)
    provenance: Provenance


class EvidenceKind(StrEnum):
    TRANSCRIPT = "transcript"
    VISUAL = "visual"
    OCR = "ocr"
    AUDIO = "audio"
    TIMELINE = "timeline"
    FRAME = "frame"


class Evidence(DomainModel):
    """支持回答结论的证据。

    `quote` 只保存字幕/OCR 原文，`description` 保存系统解释。二者分开后，验证器
    才能判断“视频直接说了什么”和“模型推断了什么”。
    """

    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    kind: EvidenceKind
    artifact_ids: list[UUID] = Field(default_factory=list)
    time_range: TimeRange | None = None
    timestamp_ms: int | None = Field(default=None, ge=0)
    frame_index: int | None = Field(default=None, ge=0)
    spatial_region: SpatialRegion | None = None
    quote: str | None = None
    description: str
    confidence: float = Field(default=1, ge=0, le=1)
    snapshot_url: str | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def require_temporal_anchor(self) -> Evidence:
        if self.time_range is None and self.timestamp_ms is None and self.frame_index is None:
            raise ValueError("Evidence 必须至少包含一个时间或帧锚点")
        return self
