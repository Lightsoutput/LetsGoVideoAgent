from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel, ModelUsage, utc_now


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    POLICY_DENIED = "policy_denied"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


class RunBudget(DomainModel):
    max_steps: int = Field(default=12, ge=1)
    max_tool_calls: int = Field(default=10, ge=1)
    max_model_calls: int = Field(default=6, ge=0)
    max_tokens: int = Field(default=12_000, ge=100)
    max_cost_usd: Decimal = Field(default=Decimal("0.10"), ge=0)
    deadline_seconds: int = Field(default=60, ge=1)
    max_repeated_tool_call: int = Field(default=2, ge=1, le=5)


class AgentStep(DomainModel):
    index: int = Field(ge=1)
    kind: str
    name: str
    status: str
    summary: str
    elapsed_ms: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class AgentRun(DomainModel):
    """可展示的运行记录，不保存模型隐藏思维链。

    Trace 只记录节点、公开工具、输入摘要、结果摘要、用量和错误。这样既可排障，
    也不会把内部推理当作产品功能暴露给前端。
    """

    id: UUID = Field(default_factory=uuid4)
    agent_name: str
    agent_version: str
    video_id: UUID
    conversation_id: UUID
    status: RunStatus = RunStatus.RUNNING
    budget: RunBudget
    usage: ModelUsage = Field(default_factory=ModelUsage)
    steps: list[AgentStep] = Field(default_factory=list)
    stop_reason: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
