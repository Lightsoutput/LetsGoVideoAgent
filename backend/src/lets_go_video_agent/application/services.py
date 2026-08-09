from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from pydantic import HttpUrl

from lets_go_video_agent.agents.graphs.qa_graph import build_qa_graph
from lets_go_video_agent.agents.harness.engine import (
    AgentHarness,
    BudgetExceededError,
    PolicyDeniedError,
)
from lets_go_video_agent.agents.harness.models import AgentRun, RunBudget, RunStatus
from lets_go_video_agent.agents.roles.evidence_verifier import EvidenceVerifier
from lets_go_video_agent.agents.roles.qa_investigator import QAInvestigator
from lets_go_video_agent.application.errors import (
    ExternalServiceUnavailableError,
    NotFoundError,
)
from lets_go_video_agent.application.ports import (
    AnswerRepository,
    RunRepository,
    TimelineRepository,
    VideoRepository,
)
from lets_go_video_agent.domain.observability import TraceEventType
from lets_go_video_agent.domain.qa import (
    Answer,
    AnswerStatus,
    GlobalTarget,
    Question,
    QuestionTarget,
)
from lets_go_video_agent.domain.timeline import TimelineArtifact
from lets_go_video_agent.domain.video import (
    UploadSource,
    Video,
    VideoStatus,
    WebSource,
)
from lets_go_video_agent.media.local_storage import LocalUploadStore
from lets_go_video_agent.media.url_policy import SourceUrlPolicy


class VideoService:
    def __init__(
        self,
        *,
        videos: VideoRepository,
        timeline: TimelineRepository,
        upload_store: LocalUploadStore,
        url_policy: SourceUrlPolicy,
    ) -> None:
        self._videos = videos
        self._timeline = timeline
        self._upload_store = upload_store
        self._url_policy = url_policy

    async def list_videos(self) -> list[Video]:
        return list(await self._videos.list())

    async def get_video(self, video_id: UUID) -> Video:
        video = await self._videos.get(video_id)
        if video is None:
            raise NotFoundError(f"未找到视频: {video_id}")
        return video

    async def get_timeline(self, video_id: UUID) -> list[TimelineArtifact]:
        await self.get_video(video_id)
        return list(await self._timeline.list_for_video(video_id))

    async def import_web(
        self,
        *,
        url: str,
        title: str | None,
        rights_confirmed: bool,
    ) -> Video:
        safe_url = self._url_policy.validate(url)
        video = Video(
            title=title or "等待读取网页元数据",
            source=WebSource(
                original_url=HttpUrl(safe_url),
                rights_confirmed=rights_confirmed,
            ),
            status=VideoStatus.CREATED,
            current_stage=(
                "queued_for_metadata"
                if rights_confirmed
                else "metadata_only_waiting_for_rights_confirmation"
            ),
        )
        await self._videos.add(video)
        return video

    async def upload(self, upload: UploadFile) -> Video:
        object_key, size, sha256 = await self._upload_store.save(upload)
        source = UploadSource(
            original_filename=Path(upload.filename or "video").name,
            content_type=upload.content_type or "application/octet-stream",
            size_bytes=size,
            sha256=sha256,
        )
        video = Video(
            title=Path(source.original_filename).stem,
            source=source,
            source_object_key=object_key,
            status=VideoStatus.CREATED,
            current_stage="queued_for_probe",
        )
        await self._videos.add(video)
        return video


class QuestionService:
    def __init__(
        self,
        *,
        videos: VideoRepository,
        answers: AnswerRepository,
        runs: RunRepository,
        harness: AgentHarness,
        investigator: QAInvestigator,
        verifier: EvidenceVerifier,
        default_budget: RunBudget,
    ) -> None:
        self._videos = videos
        self._answers = answers
        self._runs = runs
        self._harness = harness
        self._investigator = investigator
        self._verifier = verifier
        self._default_budget = default_budget
        self._graph = build_qa_graph(investigator, verifier)

    @property
    def default_budget(self) -> RunBudget:
        """向安全的运行状态 API 暴露只读副本，避免外部修改 Agent 策略。"""
        return self._default_budget.model_copy(deep=True)

    async def ask(
        self,
        *,
        video_id: UUID,
        query: str,
        target: QuestionTarget | None = None,
        conversation_id: UUID | None = None,
        use_web_search: bool = False,
    ) -> Answer:
        video = await self._videos.get(video_id)
        if video is None:
            raise NotFoundError(f"未找到视频: {video_id}")
        if use_web_search and "search_web" not in self._harness.registry.names:
            raise ExternalServiceUnavailableError(
                "已要求联网回答，但 Search MCP 尚未启用或不可用"
            )

        question = Question(
            video_id=video_id,
            conversation_id=conversation_id or uuid4(),
            query=query,
            target=target or GlobalTarget(),
            use_web_search=use_web_search,
        )
        await self._answers.add_question(question)

        run = AgentRun(
            agent_name="video_qa_graph",
            agent_version="0.1.0",
            video_id=video_id,
            conversation_id=question.conversation_id,
            budget=self._default_budget.model_copy(deep=True),
        )
        await self._runs.add_run(run)
        allowed_tools = set(self._investigator.allowed_tools) & set(
            self._harness.registry.names
        )
        session = self._harness.start_session(
            run=run,
            allowed_tools=allowed_tools,
        )
        await session.emit(
            TraceEventType.AGENT_STARTED,
            name=run.agent_name,
            status=run.status.value,
            summary="开始基于视频证据调查用户问题",
            attributes={"phase": "入口", "node_id": "video_qa_graph"},
        )

        try:
            final_state = await self._graph.ainvoke(
                {
                    "question": question,
                    "session": session,
                    "video_duration_ms": video.duration_ms,
                    "repair_count": 0,
                }
            )
            answer = Answer.model_validate(final_state["answer"])
            status = (
                RunStatus.COMPLETED
                if answer.status is AnswerStatus.ANSWERED
                else RunStatus.INSUFFICIENT_EVIDENCE
            )
            session.complete(status, answer.status.value)
            answer.usage = session.run.usage
        except BudgetExceededError as exc:
            session.complete(RunStatus.BUDGET_EXHAUSTED, str(exc))
            answer = Answer(
                question_id=question.id,
                status=AnswerStatus.ABSTAINED,
                text="本次调查已达到预算上限，基于当前证据无法给出可靠回答。",
                limitations=[str(exc)],
                trace_id=run.id,
                usage=session.run.usage,
            )
        except PolicyDeniedError as exc:
            session.complete(RunStatus.POLICY_DENIED, str(exc))
            answer = Answer(
                question_id=question.id,
                status=AnswerStatus.ABSTAINED,
                text="Agent 的工具策略拒绝了本次操作。",
                limitations=[str(exc)],
                trace_id=run.id,
                usage=session.run.usage,
            )
        except Exception as exc:
            session.complete(RunStatus.FAILED, type(exc).__name__)
            await session.emit(
                TraceEventType.AGENT_FAILED,
                name=run.agent_name,
                status=run.status.value,
                summary=type(exc).__name__,
            )
            await session.emit(
                TraceEventType.WORKFLOW_FAILED,
                name="qa_workflow_result",
                status=run.status.value,
                summary=f"问答工作流异常结束：{type(exc).__name__}",
                attributes={
                    "phase": "完成",
                    "node_id": "qa_workflow_result",
                    "depends_on": ["video_qa_graph"],
                },
            )
            await self._runs.update_run(run)
            raise

        await session.emit(
            TraceEventType.AGENT_COMPLETED,
            name=run.agent_name,
            status=run.status.value,
            summary=run.stop_reason or "Agent 运行结束",
            attributes={
                "phase": "完成",
                "node_id": "video_qa_graph",
                "depends_on": ["evidence_verifier"],
            },
        )
        await session.emit(
            (
                TraceEventType.WORKFLOW_COMPLETED
                if run.status in {RunStatus.COMPLETED, RunStatus.INSUFFICIENT_EVIDENCE}
                else TraceEventType.WORKFLOW_FAILED
            ),
            name="qa_workflow_result",
            status=run.status.value,
            summary=(
                "问答工作流已结束，回答和可回放证据已发布"
                if run.status in {RunStatus.COMPLETED, RunStatus.INSUFFICIENT_EVIDENCE}
                else f"问答工作流终止：{run.stop_reason or run.status.value}"
            ),
            attributes={
                "phase": "完成",
                "node_id": "qa_workflow_result",
                "depends_on": ["evidence_verifier"],
            },
        )
        await self._answers.add_answer(answer)
        await self._runs.update_run(run)
        return answer


def create_budget(
    *,
    max_model_calls: int,
    max_tool_calls: int,
    max_tokens: int,
    max_cost_usd: float,
    deadline_seconds: int,
) -> RunBudget:
    return RunBudget(
        max_model_calls=max_model_calls,
        max_tool_calls=max_tool_calls,
        max_tokens=max_tokens,
        max_cost_usd=Decimal(str(max_cost_usd)),
        deadline_seconds=deadline_seconds,
    )
