from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from lets_go_video_agent.agents.catalog import AGENT_CATALOG, get_agent
from lets_go_video_agent.application.errors import NotFoundError
from lets_go_video_agent.application.ports import AppStore
from lets_go_video_agent.application.services import VideoService
from lets_go_video_agent.domain.common import utc_now
from lets_go_video_agent.domain.observability import TraceEvent, TraceEventType
from lets_go_video_agent.domain.processing import ProcessingRun, ProcessingStatus
from lets_go_video_agent.domain.skill import (
    SkillBinding,
    SkillProject,
    SkillProjectAgent,
    SkillProjectAgentAssignment,
    SkillProjectChapterPreview,
    SkillProjectCostSummary,
    SkillProjectFramePreview,
    SkillProjectItem,
    SkillProjectItemStatus,
    SkillProjectModelRoute,
    SkillProjectStatus,
    SkillProjectVideoInsight,
    SkillProjectWorkspace,
    SkillStatus,
)
from lets_go_video_agent.domain.timeline import TimelineKind


class ProcessingManager(Protocol):
    def start(self, video_id: UUID) -> ProcessingRun: ...

    def get(self, video_id: UUID) -> ProcessingRun | None: ...


AGENT_ROSTER = tuple(
    agent
    for agent in AGENT_CATALOG
    if agent.id
    in {
        "ingestion_agent",
        "audio_perception_agent",
        "visual_sampling_agent",
        "ocr_perception_agent",
        "vlm_understanding_agent",
        "speaker_analysis_agent",
        "timeline_curator_agent",
        "skill_builder_agent",
    }
)

STAGE_AGENT = {
    "reading_web_metadata": "ingestion_agent",
    "downloading": "ingestion_agent",
    "downloaded": "ingestion_agent",
    "probing": "ingestion_agent",
    "transcribing": "audio_perception_agent",
    "sampling_frames": "visual_sampling_agent",
    "ocr": "ocr_perception_agent",
    "visual_understanding": "vlm_understanding_agent",
    "diarizing": "speaker_analysis_agent",
    "summarizing": "timeline_curator_agent",
}


class SkillProjectService:
    """管理垂类样本项目，并把底层处理 Trace 汇总成易读的 Agent 工位。"""

    def __init__(
        self,
        *,
        store: AppStore,
        videos: VideoService,
        processing: ProcessingManager,
        llm_provider: str = "deepseek",
        llm_model: str = "未配置",
        vlm_provider: str = "siliconflow",
        vlm_model: str = "未配置",
    ) -> None:
        self._store = store
        self._videos = videos
        self._processing = processing
        self._model_routes = [
            SkillProjectModelRoute(
                target="类别视觉规则 → 画面理解 / 当前帧问答",
                provider=vlm_provider,
                model=vlm_model,
                agent_id="vlm_understanding_agent",
                agent_display_name=get_agent("vlm_understanding_agent").display_name,
                stages=["visual_understanding", "frame_qa"],
                configured=vlm_model != "未配置",
            ),
            SkillProjectModelRoute(
                target="类别文本规则 → 字幕审核 / 分段总结",
                provider=llm_provider,
                model=llm_model,
                agent_id="timeline_curator_agent",
                agent_display_name=get_agent("timeline_curator_agent").display_name,
                stages=["subtitle_review", "timeline"],
                configured=llm_model != "未配置",
            ),
            SkillProjectModelRoute(
                target="类别问答规则 → 视频问答 / 默认答案",
                provider=llm_provider,
                model=llm_model,
                agent_id="qa_investigator",
                agent_display_name=get_agent("qa_investigator").display_name,
                stages=["qa", "default_answers"],
                configured=llm_model != "未配置",
            ),
            SkillProjectModelRoute(
                target="多样本共性 → Skill 生成 / 修订",
                provider=llm_provider,
                model=llm_model,
                agent_id="skill_builder_agent",
                agent_display_name=get_agent("skill_builder_agent").display_name,
                stages=["skill_generate", "skill_refine"],
                configured=llm_model != "未配置",
            ),
        ]

    async def list_projects(self) -> list[SkillProject]:
        return list(await self._store.list_skill_projects())

    async def create(self, *, name: str, goal: str, description: str = "") -> SkillProjectWorkspace:
        project = SkillProject(name=name, goal=goal, description=description)
        await self._store.upsert_skill_project(project)
        return await self.get(project.id)

    async def delete(self, project_id: UUID) -> None:
        await self._require_project(project_id)
        await self._store.delete_skill_project(project_id)

    async def get(self, project_id: UUID) -> SkillProjectWorkspace:
        project = await self._require_project(project_id)
        items = list(await self._store.list_skill_project_items(project_id))
        refreshed = [await self._refresh_item(item) for item in items]
        status = self._project_status(refreshed)
        if project.status is not status:
            project.status = status
            project.updated_at = utc_now()
            await self._store.upsert_skill_project(project)
        logs = await self._recent_logs(refreshed)
        cost_summary = await self._cost_summary(refreshed)
        return SkillProjectWorkspace(
            project=project,
            items=refreshed,
            agents=self._agent_snapshots(refreshed, logs),
            recent_logs=logs[-80:],
            cost_summary=cost_summary,
            model_routes=self._model_routes,
        )

    async def _cost_summary(
        self, items: Sequence[SkillProjectItem]
    ) -> SkillProjectCostSummary:
        events = []
        seen = set()
        title_by_id = {item.video_id: item.title for item in items if item.video_id}
        for video_id in title_by_id:
            for event in await self._store.list_usage_events(video_id):
                if event.id not in seen:
                    seen.add(event.id)
                    events.append(event)
        summary = SkillProjectCostSummary(
            total_cost_cny=sum((event.cost_cny for event in events), start=Decimal()),
            call_count=len(events),
            input_tokens=sum(event.input_tokens for event in events),
            output_tokens=sum(event.output_tokens for event in events),
            image_count=sum(event.image_count for event in events),
        )
        for event in events:
            agent_id = event.agent_id or self._agent_for_purpose(event.purpose)
            video_title = (
                title_by_id.get(event.video_id, "未关联视频")
                if event.video_id is not None
                else "未关联视频"
            )
            summary.by_model[event.model] = (
                summary.by_model.get(event.model, Decimal()) + event.cost_cny
            )
            summary.by_agent[get_agent(agent_id).display_name] = (
                summary.by_agent.get(get_agent(agent_id).display_name, Decimal()) + event.cost_cny
            )
            summary.by_video[video_title] = (
                summary.by_video.get(video_title, Decimal()) + event.cost_cny
            )
            summary.by_purpose[event.purpose] = (
                summary.by_purpose.get(event.purpose, Decimal()) + event.cost_cny
            )
        return summary

    @staticmethod
    def _agent_for_purpose(purpose: str) -> str:
        if "visual" in purpose or "frame" in purpose:
            return "vlm_understanding_agent"
        if purpose.startswith("skill_"):
            return "skill_builder_agent"
        if "subtitle" in purpose:
            return "ocr_perception_agent"
        return "timeline_curator_agent"

    async def add_urls(
        self,
        *,
        project_id: UUID,
        urls: Sequence[str],
        rights_confirmed: bool,
    ) -> SkillProjectWorkspace:
        project = await self._require_project(project_id)
        existing = list(await self._store.list_skill_project_items(project_id))
        identities = {self._url_identity(item.source_url) for item in existing}
        for raw_url in urls:
            url = raw_url.strip()
            if not url or self._url_identity(url) in identities:
                continue
            item = SkillProjectItem(project_id=project_id, source_url=url)
            await self._store.upsert_skill_project_item(item)
            try:
                video = await self._videos.import_web(
                    url=url,
                    title=None,
                    rights_confirmed=rights_confirmed,
                )
                item.video_id = video.id
                item.title = video.title
                video.metadata.update(
                    {
                        "library_scope": "skill-project",
                        "skill_project_id": str(project.id),
                        "skill_project_name": project.name,
                    }
                )
                await self._store.update(video)
                if video.status == "ready":
                    item.status = SkillProjectItemStatus.READY
                    item.stage = "ready"
                    item.stage_label = "可以作为样本"
                    item.progress = 1
                    item.message = "已复用视频库中的处理结果"
                elif rights_confirmed:
                    run = self._processing.start(video.id)
                    item.status = SkillProjectItemStatus.PROCESSING
                    item.trace_id = run.trace_id
                    item.stage = run.stage
                    item.stage_label = run.stage_label
                    item.message = "已分配给媒体接入 Agent"
                    item.current_agent = "ingestion_agent"
                else:
                    item.status = SkillProjectItemStatus.IMPORTING
                    item.message = "等待确认有权处理该视频"
            except Exception as exc:
                item.status = SkillProjectItemStatus.FAILED
                item.error = f"{type(exc).__name__}: {exc}"
                item.message = "导入失败，可稍后重试"
            item.updated_at = utc_now()
            await self._store.upsert_skill_project_item(item)
            identities.add(self._url_identity(url))
        project.status = SkillProjectStatus.PROCESSING
        project.updated_at = utc_now()
        await self._store.upsert_skill_project(project)
        return await self.get(project_id)

    async def retry(self, project_id: UUID, item_id: UUID) -> SkillProjectWorkspace:
        await self._require_project(project_id)
        item = await self._store.get_skill_project_item(item_id)
        if item is None or item.project_id != project_id:
            raise NotFoundError(f"未找到项目视频任务: {item_id}")
        if item.video_id is None:
            video = await self._videos.import_web(
                url=item.source_url,
                title=None,
                rights_confirmed=True,
            )
            item.video_id = video.id
            item.title = video.title
            project = await self._require_project(project_id)
            video.metadata.update(
                {
                    "library_scope": "skill-project",
                    "skill_project_id": str(project.id),
                    "skill_project_name": project.name,
                }
            )
            await self._store.update(video)
        run = self._processing.start(item.video_id)
        item.status = SkillProjectItemStatus.PROCESSING
        item.trace_id = run.trace_id
        item.stage = run.stage
        item.stage_label = run.stage_label
        item.progress = run.progress
        item.agent_tasks = run.agent_tasks
        item.current_agent = "ingestion_agent"
        item.message = "已重新进入处理流水线"
        item.error = None
        item.updated_at = utc_now()
        await self._store.upsert_skill_project_item(item)
        return await self.get(project_id)

    async def attach_skill(self, project_id: UUID, skill_id: UUID) -> SkillProjectWorkspace:
        project = await self._require_project(project_id)
        skill = await self._store.get_skill(skill_id)
        if skill is None:
            raise NotFoundError(f"未找到 Skill: {skill_id}")
        project.skill_id = skill_id
        project.updated_at = utc_now()
        await self._store.upsert_skill_project(project)
        if skill.status is SkillStatus.PUBLISHED:
            for item in await self._store.list_skill_project_items(project_id):
                if item.status is SkillProjectItemStatus.READY and item.video_id:
                    await self._store.upsert_skill_binding(
                        SkillBinding(video_id=item.video_id, skill_id=skill_id)
                    )
        return await self.get(project_id)

    async def _require_project(self, project_id: UUID) -> SkillProject:
        project = await self._store.get_skill_project(project_id)
        if project is None:
            raise NotFoundError(f"未找到 Skill 项目: {project_id}")
        return project

    async def _refresh_item(self, item: SkillProjectItem) -> SkillProjectItem:
        if item.video_id is None:
            return item
        # import_web 初次登记时可能只有占位标题；下载器读取元数据后，项目卡片应跟随
        # Video 权威记录刷新，不能把旧占位标题永久复制下来。
        video = await self._store.get(item.video_id)
        title_changed = bool(video and video.title and item.title != video.title)
        if title_changed and video is not None:
            item.title = video.title
        run = self._processing.get(item.video_id)
        if run is None:
            run = await self._store.get_processing_run(item.video_id)
        if run is None:
            if video and video.status == "ready":
                item.insight = await self._video_insight(item.video_id)
            if title_changed:
                item.updated_at = utc_now()
                await self._store.upsert_skill_project_item(item)
            return item
        next_status = {
            ProcessingStatus.QUEUED: SkillProjectItemStatus.QUEUED,
            ProcessingStatus.RUNNING: SkillProjectItemStatus.PROCESSING,
            ProcessingStatus.COMPLETED: SkillProjectItemStatus.READY,
            ProcessingStatus.FAILED: SkillProjectItemStatus.FAILED,
        }[run.status]
        running_tasks = [task for task in run.agent_tasks if task.status == "running"]
        current_agent = (
            running_tasks[0].agent_id if running_tasks else STAGE_AGENT.get(run.stage)
        )
        next_message = (
            "；".join(
                f"{task.agent_number} {task.display_name}：{task.message}"
                for task in running_tasks[:3]
            )
            or run.message
        )
        changed = (
            title_changed
            or item.status is not next_status
            or item.progress != run.progress
            or item.stage != run.stage
            or item.message != next_message
        )
        item.status = next_status
        item.trace_id = run.trace_id
        item.stage = run.stage
        item.stage_label = run.stage_label
        item.progress = run.progress
        item.current_agent = (
            current_agent if next_status is SkillProjectItemStatus.PROCESSING else None
        )
        item.message = next_message
        item.error = run.error
        if changed:
            item.updated_at = utc_now()
            await self._store.upsert_skill_project_item(item)
        if next_status is SkillProjectItemStatus.READY:
            item.insight = await self._video_insight(item.video_id)
            project = await self._store.get_skill_project(item.project_id)
            skill = (
                await self._store.get_skill(project.skill_id)
                if project and project.skill_id
                else None
            )
            if skill and skill.status is SkillStatus.PUBLISHED:
                # 项目 Skill 自动覆盖该项目中已经完成理解的视频；后续新视频完成时也会绑定。
                await self._store.upsert_skill_binding(
                    SkillBinding(video_id=item.video_id, skill_id=skill.id)
                )
        return item

    async def _video_insight(self, video_id: UUID) -> SkillProjectVideoInsight:
        """把已完成理解的权威结果投影到项目卡片，不重复调用任何模型。"""

        narrative = await self._store.get_narrative_context(video_id)
        artifacts = await self._store.list_for_video(video_id)
        chapters = sorted(
            (item for item in artifacts if item.kind is TimelineKind.CHAPTER),
            key=lambda item: item.time_range.start_ms,
        )[:20]
        frames = sorted(
            (
                item
                for item in artifacts
                if item.kind is TimelineKind.VISUAL
                and "representative-frame" in item.tags
            ),
            key=lambda item: item.time_range.start_ms,
        )[:8]
        return SkillProjectVideoInsight(
            video_format=narrative.video_format if narrative else "通用视频",
            purpose=narrative.purpose if narrative else "",
            summary=narrative.summary[:3_000] if narrative else "",
            themes=narrative.themes[:12] if narrative else [],
            chapters=[
                SkillProjectChapterPreview(
                    title=item.title or "未命名章节",
                    summary=item.text[:1_000],
                    start_ms=item.time_range.start_ms,
                    end_ms=item.time_range.end_ms,
                )
                for item in chapters
            ],
            representative_frames=[
                SkillProjectFramePreview(
                    title=item.title or "代表画面",
                    description=item.text[:1_000],
                    timestamp_ms=item.time_range.start_ms,
                    snapshot_filename=(
                        item.snapshot_key.replace("\\", "/").rsplit("/", 1)[-1]
                        if item.snapshot_key
                        else None
                    ),
                )
                for item in frames
            ],
        )

    async def _recent_logs(self, items: Sequence[SkillProjectItem]) -> list[TraceEvent]:
        logs: list[TraceEvent] = []
        for item in items:
            if item.trace_id:
                logs.extend(await self._store.list_trace_events(item.trace_id))
        return sorted(logs, key=lambda event: event.occurred_at)

    @staticmethod
    def _agent_snapshots(
        items: Sequence[SkillProjectItem], logs: Sequence[TraceEvent]
    ) -> list[SkillProjectAgent]:
        latest: dict[str, TraceEvent] = {}
        active_by_agent: dict[str, list[TraceEvent]] = {}
        videos: dict[UUID, SkillProjectItem] = {
            item.video_id: item for item in items if item.video_id is not None
        }
        latest_by_trace_agent: dict[tuple[UUID, str], TraceEvent] = {}
        for event in logs:
            if event.agent_id:
                latest[event.agent_id] = event
                latest_by_trace_agent[(event.trace_id, event.agent_id)] = event
        for event in latest_by_trace_agent.values():
            if event.event_type is TraceEventType.AGENT_STARTED and event.status == "running":
                active_by_agent.setdefault(event.agent_id or "", []).append(event)
        result: list[SkillProjectAgent] = []
        for agent in AGENT_ROSTER:
            agent_id = agent.id
            assignments = [
                SkillProjectAgentAssignment(
                    video_id=item.video_id,
                    video_title=item.title,
                    trace_id=item.trace_id,
                    task=agent_task.task,
                    message=agent_task.message,
                    progress=agent_task.progress,
                    completed_units=agent_task.completed_units,
                    total_units=agent_task.total_units,
                )
                for item in items
                if item.video_id is not None
                for agent_task in item.agent_tasks
                if agent_task.agent_id == agent_id and agent_task.status == "running"
            ]
            active_events = active_by_agent.get(agent_id, [])
            assigned_items = [item for item in items if item.current_agent == agent_id]
            active_event: TraceEvent | None = active_events[-1] if active_events else None
            working = (
                videos.get(active_event.video_id)
                if active_event and active_event.video_id is not None
                else next((item for item in items if item.current_agent == agent_id), None)
            )
            latest_event = latest.get(agent_id)
            event_item = (
                videos.get(latest_event.video_id)
                if latest_event and latest_event.video_id is not None
                else None
            )
            if working:
                active_task = next(
                    (
                        task
                        for task in working.agent_tasks
                        if task.agent_id == agent_id and task.status == "running"
                    ),
                    None,
                )
                result.append(
                    SkillProjectAgent(
                        id=agent_id,
                        display_name=agent.display_name,
                        role=agent.role,
                        avatar=agent.avatar,
                        status="working",
                        video_id=working.video_id,
                        video_title=working.title,
                        task=active_task.task if active_task else working.stage_label,
                        message=active_task.message if active_task else working.message,
                        progress=active_task.progress if active_task else working.progress,
                        trace_id=working.trace_id,
                        active_tasks=max(
                            1, len(assignments), len(active_events), len(assigned_items)
                        ),
                        completed_units=active_task.completed_units if active_task else 0,
                        total_units=active_task.total_units if active_task else None,
                        model_provider=active_task.model_provider if active_task else None,
                        model=active_task.model if active_task else None,
                        assignments=assignments,
                    )
                )
            elif latest_event and latest_event.event_type is TraceEventType.AGENT_FAILED:
                result.append(
                    SkillProjectAgent(
                        id=agent_id,
                        display_name=agent.display_name,
                        role=agent.role,
                        avatar=agent.avatar,
                        status="attention",
                        video_id=latest_event.video_id,
                        video_title=event_item.title if event_item else None,
                        task=latest_event.summary,
                        message=latest_event.summary,
                        trace_id=latest_event.trace_id,
                    )
                )
            else:
                result.append(
                    SkillProjectAgent(
                        id=agent_id,
                        display_name=agent.display_name,
                        role=agent.role,
                        avatar=agent.avatar,
                        status="idle",
                        task="等待流水线任务",
                        message="没有待处理的样本任务",
                    )
                )
        return result

    @staticmethod
    def _project_status(items: Sequence[SkillProjectItem]) -> SkillProjectStatus:
        if any(item.status is SkillProjectItemStatus.FAILED for item in items):
            return SkillProjectStatus.ATTENTION
        if any(
            item.status in {
                SkillProjectItemStatus.QUEUED,
                SkillProjectItemStatus.IMPORTING,
                SkillProjectItemStatus.PROCESSING,
            }
            for item in items
        ):
            return SkillProjectStatus.PROCESSING
        if items and all(item.status is SkillProjectItemStatus.READY for item in items):
            return SkillProjectStatus.READY
        return SkillProjectStatus.ACTIVE

    @staticmethod
    def _url_identity(url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", "")
        )
