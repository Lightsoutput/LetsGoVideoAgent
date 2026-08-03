from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from lets_go_video_agent.agents.harness.tools import ToolRegistry, ToolSpec
from lets_go_video_agent.application.ports import FrameInspectionPort, RetrievalPort
from lets_go_video_agent.domain.common import DomainModel
from lets_go_video_agent.domain.qa import QuestionTarget
from lets_go_video_agent.domain.timeline import Evidence


class SearchTimelineInput(DomainModel):
    video_id: UUID
    query: str = Field(min_length=1, max_length=2_000)
    target: QuestionTarget
    limit: int = Field(default=8, ge=1, le=30)


class InspectFrameInput(DomainModel):
    video_id: UUID
    timestamp_ms: int = Field(ge=0)
    query: str = Field(min_length=1, max_length=2_000)


class EvidenceBatch(DomainModel):
    items: list[Evidence]


def build_video_tool_registry(
    retrieval: RetrievalPort,
    frame_inspector: FrameInspectionPort,
) -> ToolRegistry:
    registry = ToolRegistry()

    async def search_timeline(payload: BaseModel) -> EvidenceBatch:
        args = SearchTimelineInput.model_validate(payload)
        items = await retrieval.search(
            video_id=args.video_id,
            query=args.query,
            target=args.target,
            limit=args.limit,
        )
        return EvidenceBatch(items=list(items))

    async def inspect_frame(payload: BaseModel) -> EvidenceBatch:
        args = InspectFrameInput.model_validate(payload)
        items = await frame_inspector.inspect(
            video_id=args.video_id,
            timestamp_ms=args.timestamp_ms,
            query=args.query,
        )
        return EvidenceBatch(items=list(items))

    registry.register(
        ToolSpec(
            name="search_timeline",
            description="按问题和时间范围检索字幕、OCR、章节及视觉证据",
            input_model=SearchTimelineInput,
            output_model=EvidenceBatch,
            handler=search_timeline,
        )
    )
    registry.register(
        ToolSpec(
            name="inspect_frame",
            description="检查指定时间戳附近的原始帧、OCR 与视觉描述",
            input_model=InspectFrameInput,
            output_model=EvidenceBatch,
            handler=inspect_frame,
        )
    )
    return registry
