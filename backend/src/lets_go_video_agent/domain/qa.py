from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from lets_go_video_agent.domain.common import DomainModel, ModelUsage, TimeRange, utc_now
from lets_go_video_agent.domain.timeline import Evidence, EvidenceKind


class GlobalTarget(DomainModel):
    kind: Literal["global"] = "global"


class RangeTarget(DomainModel):
    kind: Literal["range"] = "range"
    time_range: TimeRange


class MomentTarget(DomainModel):
    kind: Literal["moment"] = "moment"
    timestamp_ms: int = Field(ge=0)
    context_window_ms: int = Field(default=8_000, ge=1_000, le=60_000)

    @field_validator("timestamp_ms", mode="before")
    @classmethod
    def round_timestamp(cls, value: object) -> object:
        return round(value) if isinstance(value, float) else value


class FrameTarget(DomainModel):
    kind: Literal["frame"] = "frame"
    timestamp_ms: int = Field(ge=0)

    @field_validator("timestamp_ms", mode="before")
    @classmethod
    def round_timestamp(cls, value: object) -> object:
        return round(value) if isinstance(value, float) else value


QuestionTarget = Annotated[
    GlobalTarget | RangeTarget | MomentTarget | FrameTarget,
    Field(discriminator="kind"),
]


class Question(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    conversation_id: UUID = Field(default_factory=uuid4)
    query: str = Field(min_length=1, max_length=2_000)
    target: QuestionTarget = Field(default_factory=GlobalTarget)
    requested_evidence_types: list[EvidenceKind] = Field(default_factory=list)
    use_web_search: bool = False
    # 仅保存已发布 Skill 的压缩运行时上下文；草案永远不会进入问答。
    skill_id: UUID | None = None
    skill_version: int | None = Field(default=None, ge=1)
    skill_name: str | None = Field(default=None, max_length=120)
    skill_context: str | None = Field(default=None, max_length=8_000)
    created_at: datetime = Field(default_factory=utc_now)


class WebReference(DomainModel):
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=8, max_length=2_048)
    content: str = Field(default="", max_length=2_000)


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    PARTIAL = "partial"
    ABSTAINED = "abstained"


class EvidenceCitation(DomainModel):
    evidence_id: UUID
    timestamp_ms: int = Field(ge=0)
    label: str
    snapshot_url: str | None = None


class Answer(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    question_id: UUID
    status: AnswerStatus
    text: str
    citations: list[EvidenceCitation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)
    web_search_performed: bool = False
    web_sources: list[WebReference] = Field(default_factory=list)
    trace_id: UUID
    usage: ModelUsage = Field(default_factory=ModelUsage)
    skill_id: UUID | None = None
    skill_version: int | None = Field(default=None, ge=1)
    skill_name: str | None = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def answered_requires_evidence(self) -> Answer:
        if self.status == AnswerStatus.ANSWERED and not self.citations:
            raise ValueError("确定回答必须至少引用一条证据")
        return self
