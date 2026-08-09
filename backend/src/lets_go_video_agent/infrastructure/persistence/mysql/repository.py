from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lets_go_video_agent.agents.harness.models import AgentRun
from lets_go_video_agent.application.ports import RunRecord
from lets_go_video_agent.domain.observability import TraceEvent, UsageEvent
from lets_go_video_agent.domain.processing import ProcessingRun
from lets_go_video_agent.domain.qa import Answer, Question
from lets_go_video_agent.domain.semantic import NarrativeContext, SemanticEvent
from lets_go_video_agent.domain.timeline import TimelineArtifact
from lets_go_video_agent.domain.video import Video
from lets_go_video_agent.infrastructure.persistence.mysql.models import (
    AgentRunRow,
    AnswerRow,
    NarrativeContextRow,
    ProcessingJobRow,
    QuestionRow,
    SemanticEventRow,
    TimelineArtifactRow,
    TraceEventRow,
    UsageEventRow,
    VideoRow,
)


class MySqlStore:
    """MySQL 8.4 权威事实库。

    热查询字段拆成普通列，完整领域对象保存在 JSON `payload`。这样 P0 可以快速迭代
    模型字段，同时仍能对状态、视频、时间和会话建立可靠索引。Qdrant 中的向量只是
    可重建派生数据，不承担业务事实来源。
    """

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            echo=echo,
            pool_pre_ping=True,
            pool_recycle=1_800,
        )
        self.sessions = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self.engine.dispose()

    async def add(self, video: Video) -> None:
        async with self.sessions.begin() as session:
            await session.merge(self._video_row(video))

    async def get(self, video_id: UUID) -> Video | None:
        async with self.sessions() as session:
            row = await session.get(VideoRow, str(video_id))
            return Video.model_validate(row.payload) if row else None

    async def list(self) -> Sequence[Video]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(select(VideoRow).order_by(VideoRow.created_at.desc()))
            ).all()
            return [Video.model_validate(row.payload) for row in rows]

    async def update(self, video: Video) -> None:
        await self.add(video)

    async def add_many(self, artifacts: Sequence[TimelineArtifact]) -> None:
        async with self.sessions.begin() as session:
            for artifact in artifacts:
                await session.merge(
                    TimelineArtifactRow(
                        id=str(artifact.id),
                        video_id=str(artifact.video_id),
                        kind=artifact.kind.value,
                        start_ms=artifact.time_range.start_ms,
                        end_ms=artifact.time_range.end_ms,
                        text=artifact.text,
                        payload=artifact.model_dump(mode="json"),
                    )
                )

    async def list_for_video(self, video_id: UUID) -> Sequence[TimelineArtifact]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(TimelineArtifactRow)
                    .where(TimelineArtifactRow.video_id == str(video_id))
                    .order_by(
                        TimelineArtifactRow.start_ms,
                        TimelineArtifactRow.kind,
                    )
                )
            ).all()
            return [TimelineArtifact.model_validate(row.payload) for row in rows]

    async def add_question(self, question: Question) -> None:
        async with self.sessions.begin() as session:
            await session.merge(
                QuestionRow(
                    id=str(question.id),
                    video_id=str(question.video_id),
                    conversation_id=str(question.conversation_id),
                    payload=question.model_dump(mode="json"),
                    created_at=question.created_at,
                )
            )

    async def add_answer(self, answer: Answer) -> None:
        async with self.sessions.begin() as session:
            await session.merge(
                AnswerRow(
                    id=str(answer.id),
                    question_id=str(answer.question_id),
                    status=answer.status.value,
                    trace_id=str(answer.trace_id),
                    payload=answer.model_dump(mode="json"),
                    created_at=answer.created_at,
                )
            )

    async def get_answer(self, answer_id: UUID) -> Answer | None:
        async with self.sessions() as session:
            row = await session.get(AnswerRow, str(answer_id))
            return Answer.model_validate(row.payload) if row else None

    async def add_run(self, run: RunRecord) -> None:
        agent_run = AgentRun.model_validate(run)
        async with self.sessions.begin() as session:
            await session.merge(
                AgentRunRow(
                    id=str(agent_run.id),
                    video_id=str(agent_run.video_id),
                    conversation_id=str(agent_run.conversation_id),
                    status=agent_run.status.value,
                    payload=agent_run.model_dump(mode="json"),
                    started_at=agent_run.started_at,
                    finished_at=agent_run.finished_at,
                )
            )

    async def update_run(self, run: RunRecord) -> None:
        await self.add_run(run)

    async def get_run(self, run_id: UUID) -> RunRecord | None:
        async with self.sessions() as session:
            row = await session.get(AgentRunRow, str(run_id))
            return AgentRun.model_validate(row.payload) if row else None

    async def upsert_processing_run(self, run: ProcessingRun) -> None:
        async with self.sessions.begin() as session:
            await session.merge(
                ProcessingJobRow(
                    id=str(run.id),
                    video_id=str(run.video_id),
                    trace_id=str(run.trace_id),
                    status=run.status.value,
                    stage=run.stage,
                    progress=run.progress,
                    payload=run.model_dump(mode="json"),
                    created_at=run.created_at,
                    finished_at=run.finished_at,
                )
            )

    async def get_processing_run(self, video_id: UUID) -> ProcessingRun | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(ProcessingJobRow).where(ProcessingJobRow.video_id == str(video_id))
            )
            return ProcessingRun.model_validate(row.payload) if row else None

    async def replace_semantic_events(
        self, video_id: UUID, events: Sequence[SemanticEvent]
    ) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                delete(SemanticEventRow).where(SemanticEventRow.video_id == str(video_id))
            )
            for event in events:
                await session.merge(
                    SemanticEventRow(
                        id=str(event.id),
                        video_id=str(event.video_id),
                        event_type=event.event_type,
                        start_ms=event.time_range.start_ms,
                        end_ms=event.time_range.end_ms,
                        confidence=event.confidence,
                        payload=event.model_dump(mode="json"),
                    )
                )

    async def list_semantic_events(self, video_id: UUID) -> Sequence[SemanticEvent]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(SemanticEventRow)
                    .where(SemanticEventRow.video_id == str(video_id))
                    .order_by(SemanticEventRow.start_ms)
                )
            ).all()
            return [SemanticEvent.model_validate(row.payload) for row in rows]

    async def upsert_narrative_context(self, context: NarrativeContext) -> None:
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(NarrativeContextRow).where(
                    NarrativeContextRow.video_id == str(context.video_id)
                )
            )
            row_id = existing.id if existing else str(context.id)
            await session.merge(
                NarrativeContextRow(
                    id=row_id,
                    video_id=str(context.video_id),
                    video_format=context.video_format,
                    version=context.version,
                    confidence=context.confidence,
                    payload=context.model_dump(mode="json"),
                )
            )

    async def get_narrative_context(self, video_id: UUID) -> NarrativeContext | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(NarrativeContextRow).where(
                    NarrativeContextRow.video_id == str(video_id)
                )
            )
            return NarrativeContext.model_validate(row.payload) if row else None

    async def append_trace_event(self, event: TraceEvent) -> None:
        async with self.sessions.begin() as session:
            await session.merge(
                TraceEventRow(
                    id=str(event.id),
                    trace_id=str(event.trace_id),
                    sequence=event.sequence,
                    event_type=event.event_type.value,
                    video_id=str(event.video_id) if event.video_id else None,
                    task_id=str(event.task_id) if event.task_id else None,
                    agent_id=event.agent_id,
                    payload=event.model_dump(mode="json"),
                    occurred_at=event.occurred_at,
                )
            )

    async def list_trace_events(self, trace_id: UUID) -> Sequence[TraceEvent]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(TraceEventRow)
                    .where(TraceEventRow.trace_id == str(trace_id))
                    .order_by(TraceEventRow.sequence, TraceEventRow.occurred_at)
                )
            ).all()
            return [TraceEvent.model_validate(row.payload) for row in rows]

    async def append_usage_event(self, event: UsageEvent) -> None:
        async with self.sessions.begin() as session:
            await session.merge(
                UsageEventRow(
                    id=str(event.id),
                    provider=event.provider,
                    model=event.model,
                    purpose=event.purpose,
                    video_id=str(event.video_id) if event.video_id else None,
                    trace_id=str(event.trace_id) if event.trace_id else None,
                    task_id=str(event.task_id) if event.task_id else None,
                    cost_cny=event.cost_cny,
                    payload=event.model_dump(mode="json"),
                    occurred_at=event.occurred_at,
                )
            )

    async def list_usage_events(self, video_id: UUID | None = None) -> Sequence[UsageEvent]:
        async with self.sessions() as session:
            statement = select(UsageEventRow)
            if video_id is not None:
                statement = statement.where(UsageEventRow.video_id == str(video_id))
            rows = (await session.scalars(statement.order_by(UsageEventRow.occurred_at))).all()
            return [UsageEvent.model_validate(row.payload) for row in rows]

    @staticmethod
    def _video_row(video: Video) -> VideoRow:
        return VideoRow(
            id=str(video.id),
            title=video.title,
            status=video.status,
            source_kind=video.source.kind,
            duration_ms=video.duration_ms,
            progress=video.progress,
            source_object_key=video.source_object_key,
            version=video.version,
            payload=video.model_dump(mode="json"),
            created_at=video.created_at,
            updated_at=video.updated_at,
        )
