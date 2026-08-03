from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lets_go_video_agent.agents.harness.models import AgentRun
from lets_go_video_agent.application.ports import RunRecord
from lets_go_video_agent.domain.qa import Answer, Question
from lets_go_video_agent.domain.timeline import TimelineArtifact
from lets_go_video_agent.domain.video import Video
from lets_go_video_agent.infrastructure.persistence.mysql.models import (
    AgentRunRow,
    AnswerRow,
    QuestionRow,
    TimelineArtifactRow,
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
