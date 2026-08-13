from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from lets_go_video_agent.domain.observability import TraceEvent, UsageEvent
from lets_go_video_agent.domain.processing import ProcessingRun
from lets_go_video_agent.domain.qa import Answer, Question, QuestionTarget
from lets_go_video_agent.domain.semantic import NarrativeContext, SemanticEvent
from lets_go_video_agent.domain.skill import (
    Skill,
    SkillBinding,
    SkillProject,
    SkillProjectItem,
    SkillVersion,
)
from lets_go_video_agent.domain.timeline import Evidence, TimelineArtifact
from lets_go_video_agent.domain.video import Video


class VideoRepository(Protocol):
    async def add(self, video: Video) -> None: ...

    async def get(self, video_id: UUID) -> Video | None: ...

    async def list(self) -> Sequence[Video]: ...

    async def update(self, video: Video) -> None: ...

    async def delete(self, video_id: UUID) -> None: ...


class TimelineRepository(Protocol):
    async def add_many(self, artifacts: Sequence[TimelineArtifact]) -> None: ...

    async def list_for_video(self, video_id: UUID) -> Sequence[TimelineArtifact]: ...


class AnswerRepository(Protocol):
    async def add_question(self, question: Question) -> None: ...

    async def add_answer(self, answer: Answer) -> None: ...

    async def get_answer(self, answer_id: UUID) -> Answer | None: ...


class RetrievalPort(Protocol):
    """Agent 只看到抽象检索端口，不知道背后是内存、MySQL 还是 Qdrant。"""

    async def search(
        self,
        *,
        video_id: UUID,
        query: str,
        target: QuestionTarget,
        limit: int,
    ) -> Sequence[Evidence]: ...


class FrameInspectionPort(Protocol):
    async def inspect(
        self,
        *,
        video_id: UUID,
        timestamp_ms: int,
        query: str,
        trace_id: UUID | None = None,
    ) -> Sequence[Evidence]: ...


class WebSearchPort(Protocol):
    """联网搜索的最小能力契约；具体实现可以是 MCP 或 SearXNG。"""

    async def health(self) -> bool: ...

    async def search(
        self, query: str, *, limit: int = 5, language: str = "zh-CN"
    ) -> list[dict[str, str]]: ...


class RunRecord(Protocol):
    id: UUID


class RunRepository(Protocol):
    async def add_run(self, run: RunRecord) -> None: ...

    async def update_run(self, run: RunRecord) -> None: ...

    async def get_run(self, run_id: UUID) -> RunRecord | None: ...


class ProcessingRunRepository(Protocol):
    async def upsert_processing_run(self, run: ProcessingRun) -> None: ...

    async def get_processing_run(self, video_id: UUID) -> ProcessingRun | None: ...


class SemanticRepository(Protocol):
    async def replace_semantic_events(
        self, video_id: UUID, events: Sequence[SemanticEvent]
    ) -> None: ...

    async def list_semantic_events(self, video_id: UUID) -> Sequence[SemanticEvent]: ...

    async def upsert_narrative_context(self, context: NarrativeContext) -> None: ...

    async def get_narrative_context(self, video_id: UUID) -> NarrativeContext | None: ...


class ObservabilityRepository(Protocol):
    async def append_trace_event(self, event: TraceEvent) -> None: ...

    async def list_trace_events(self, trace_id: UUID) -> Sequence[TraceEvent]: ...

    async def append_usage_event(self, event: UsageEvent) -> None: ...

    async def list_usage_events(
        self,
        video_id: UUID | None = None,
        trace_id: UUID | None = None,
    ) -> Sequence[UsageEvent]: ...


class SkillRepository(Protocol):
    async def upsert_skill(self, skill: Skill) -> None: ...

    async def get_skill(self, skill_id: UUID) -> Skill | None: ...

    async def list_skills(self) -> Sequence[Skill]: ...

    async def delete_skill(self, skill_id: UUID) -> None: ...

    async def add_skill_version(self, version: SkillVersion) -> None: ...

    async def get_skill_version(self, skill_id: UUID, version: int) -> SkillVersion | None: ...

    async def list_skill_versions(self, skill_id: UUID) -> Sequence[SkillVersion]: ...

    async def upsert_skill_binding(self, binding: SkillBinding) -> None: ...

    async def delete_skill_binding(self, video_id: UUID) -> None: ...

    async def get_skill_binding(self, video_id: UUID) -> SkillBinding | None: ...

    async def list_skill_bindings(self, skill_id: UUID | None = None) -> Sequence[SkillBinding]: ...

    async def upsert_skill_project(self, project: SkillProject) -> None: ...

    async def get_skill_project(self, project_id: UUID) -> SkillProject | None: ...

    async def list_skill_projects(self) -> Sequence[SkillProject]: ...

    async def delete_skill_project(self, project_id: UUID) -> None: ...

    async def upsert_skill_project_item(self, item: SkillProjectItem) -> None: ...

    async def get_skill_project_item(self, item_id: UUID) -> SkillProjectItem | None: ...

    async def list_skill_project_items(
        self, project_id: UUID
    ) -> Sequence[SkillProjectItem]: ...


class AppStore(
    VideoRepository,
    TimelineRepository,
    AnswerRepository,
    RunRepository,
    ProcessingRunRepository,
    SemanticRepository,
    ObservabilityRepository,
    SkillRepository,
    Protocol,
):
    """应用使用的组合仓库契约，memory 与 mysql 必须具有相同语义。"""

    async def ping(self) -> None: ...

    async def close(self) -> None: ...
