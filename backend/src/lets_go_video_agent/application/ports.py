from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from lets_go_video_agent.domain.qa import Answer, Question, QuestionTarget
from lets_go_video_agent.domain.timeline import Evidence, TimelineArtifact
from lets_go_video_agent.domain.video import Video


class VideoRepository(Protocol):
    async def add(self, video: Video) -> None: ...

    async def get(self, video_id: UUID) -> Video | None: ...

    async def list(self) -> Sequence[Video]: ...

    async def update(self, video: Video) -> None: ...


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
    ) -> Sequence[Evidence]: ...


class RunRecord(Protocol):
    id: UUID


class RunRepository(Protocol):
    async def add_run(self, run: RunRecord) -> None: ...

    async def update_run(self, run: RunRecord) -> None: ...

    async def get_run(self, run_id: UUID) -> RunRecord | None: ...


class AppStore(
    VideoRepository,
    TimelineRepository,
    AnswerRepository,
    RunRepository,
    Protocol,
):
    """应用使用的组合仓库契约，memory 与 mysql 必须具有相同语义。"""

    async def ping(self) -> None: ...

    async def close(self) -> None: ...
