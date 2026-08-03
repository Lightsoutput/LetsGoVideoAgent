from __future__ import annotations

from uuid import UUID

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel
from lets_go_video_agent.domain.qa import GlobalTarget, QuestionTarget
from lets_go_video_agent.domain.timeline import TimelineArtifact
from lets_go_video_agent.domain.video import Video


class WebImportRequest(DomainModel):
    url: str = Field(min_length=8, max_length=2_048)
    title: str | None = Field(default=None, max_length=300)
    rights_confirmed: bool = False


class AskQuestionRequest(DomainModel):
    query: str = Field(min_length=1, max_length=2_000)
    target: QuestionTarget = Field(default_factory=GlobalTarget)
    conversation_id: UUID | None = None


class VideoListResponse(DomainModel):
    items: list[Video]


class TimelineResponse(DomainModel):
    video_id: UUID
    items: list[TimelineArtifact]


class HealthResponse(DomainModel):
    status: str
    version: str
    repository: str


class ProblemDetail(DomainModel):
    type: str
    title: str
    status: int
    detail: str
    code: str
