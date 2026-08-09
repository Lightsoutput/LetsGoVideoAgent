from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel, utc_now


class TraceEventType(StrEnum):
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    MODEL_REQUESTED = "model.requested"
    MODEL_COMPLETED = "model.completed"
    TOOL_CALLED = "tool.called"
    TOOL_RETURNED = "tool.returned"
    MCP_CALLED = "mcp.called"
    MCP_RETURNED = "mcp.returned"
    SKILL_LOADED = "skill.loaded"
    SKILL_VALIDATED = "skill.validated"
    BUDGET_UPDATED = "budget.updated"
    HUMAN_APPROVED = "human.approved"
    HUMAN_REJECTED = "human.rejected"
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"


class TraceEvent(DomainModel):
    """可持久化、可展示的公开执行事件，不保存隐藏思维链。"""

    id: UUID = Field(default_factory=uuid4)
    trace_id: UUID
    sequence: int = Field(ge=1)
    event_type: TraceEventType
    name: str = Field(min_length=1, max_length=160)
    status: str | None = Field(default=None, max_length=40)
    summary: str = Field(default="", max_length=1_000)
    video_id: UUID | None = None
    task_id: UUID | None = None
    agent_id: str | None = Field(default=None, max_length=160)
    parent_event_id: UUID | None = None
    attributes: dict[str, object] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utc_now)


class UsageEvent(DomainModel):
    """所有模型和外部 API 共用的计费事件，统一以人民币汇总。"""

    id: UUID = Field(default_factory=uuid4)
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=160)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    image_count: int = Field(default=0, ge=0)
    request_count: int = Field(default=1, ge=1)
    original_currency: str = Field(default="CNY", min_length=3, max_length=3)
    original_cost: Decimal = Field(default=Decimal("0"), ge=0)
    cost_cny: Decimal = Field(default=Decimal("0"), ge=0)
    cache_hit: bool = False
    retry: bool = False
    status: str = Field(default="completed", max_length=40)
    pricing_version: str | None = Field(default=None, max_length=160)
    trace_id: UUID | None = None
    task_id: UUID | None = None
    video_id: UUID | None = None
    agent_id: str | None = Field(default=None, max_length=160)
    occurred_at: datetime = Field(default_factory=utc_now)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
