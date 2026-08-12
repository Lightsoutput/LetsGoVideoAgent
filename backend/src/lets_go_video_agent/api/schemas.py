from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel
from lets_go_video_agent.domain.observability import TraceEvent, UsageEvent
from lets_go_video_agent.domain.qa import GlobalTarget, QuestionTarget
from lets_go_video_agent.domain.semantic import NarrativeContext, SemanticEvent
from lets_go_video_agent.domain.skill import Skill
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
    # 前端预生成运行 ID，发出问题后即可立即订阅 Trace，而不必等待完整回答返回。
    trace_id: UUID | None = None
    use_web_search: bool = False


class VideoListResponse(DomainModel):
    items: list[Video]


class GenerateSkillRequest(DomainModel):
    video_ids: list[UUID] = Field(min_length=1, max_length=8)
    goal: str = Field(min_length=4, max_length=2_000)
    display_name: str | None = Field(default=None, max_length=120)


class RefineSkillRequest(DomainModel):
    instruction: str = Field(min_length=2, max_length=2_000)
    base_version: int | None = Field(default=None, ge=1)


class BindSkillRequest(DomainModel):
    video_ids: list[UUID] = Field(min_length=1, max_length=100)


class RollbackSkillRequest(DomainModel):
    version: int = Field(ge=1)


class SkillListResponse(DomainModel):
    items: list[Skill]


class TimelineResponse(DomainModel):
    video_id: UUID
    items: list[TimelineArtifact]


class SemanticEventsResponse(DomainModel):
    video_id: UUID
    items: list[SemanticEvent]


class NarrativeContextResponse(DomainModel):
    video_id: UUID
    context: NarrativeContext | None


class TraceEventsResponse(DomainModel):
    trace_id: UUID
    items: list[TraceEvent]


class UsageEventsResponse(DomainModel):
    items: list[UsageEvent]
    call_count: int = Field(ge=0)
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)
    total_cost_cny: Decimal = Field(ge=0)
    cost_by_provider: dict[str, Decimal]
    cost_by_model: dict[str, Decimal]


class HarnessPolicyResponse(DomainModel):
    max_steps: int = Field(ge=1)
    max_model_calls: int = Field(ge=0)
    max_tool_calls: int = Field(ge=1)
    max_tokens: int = Field(ge=100)
    max_cost_usd: Decimal = Field(ge=0)
    deadline_seconds: int = Field(ge=1)
    max_repeated_tool_call: int = Field(ge=1)
    registered_tools: list[str]


class McpStatusResponse(DomainModel):
    provider: str
    status: str
    endpoint: str | None
    tools: list[str]


class ModelRouteResponse(DomainModel):
    capability: str
    provider: str
    model: str
    configured: bool


class RuntimeComponentResponse(DomainModel):
    """状态机可视化所需的运行组件快照，不包含任何凭据。"""

    id: str
    name: str
    kind: str
    status: str
    summary: str
    endpoint: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class SystemObservabilityResponse(DomainModel):
    harness: HarnessPolicyResponse
    mcp: McpStatusResponse
    models: list[ModelRouteResponse]
    repository: str
    workflow: str
    runtime_components: list[RuntimeComponentResponse]


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
