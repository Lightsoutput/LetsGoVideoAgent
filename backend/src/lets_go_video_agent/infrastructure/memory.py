from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from lets_go_video_agent.application.ports import RunRecord, TimelineRepository
from lets_go_video_agent.domain.common import Provenance, TimeRange, utc_now
from lets_go_video_agent.domain.observability import TraceEvent, UsageEvent
from lets_go_video_agent.domain.processing import ProcessingRun, ProcessingStatus
from lets_go_video_agent.domain.qa import (
    Answer,
    FrameTarget,
    GlobalTarget,
    MomentTarget,
    Question,
    QuestionTarget,
    RangeTarget,
)
from lets_go_video_agent.domain.semantic import NarrativeContext, SemanticEvent
from lets_go_video_agent.domain.skill import Skill, SkillBinding, SkillVersion
from lets_go_video_agent.domain.timeline import (
    Evidence,
    EvidenceKind,
    TimelineArtifact,
    TimelineKind,
)
from lets_go_video_agent.domain.video import Video, VideoStatus
from lets_go_video_agent.media.video_library import resolve_video_source


class InMemoryStore:
    """开发态仓库，同时实现多个 Port。

    这是一个可替换适配器，不是“临时绕过架构”的全局字典。应用层只依赖 Port，
    Docker 模式会在装配点换成 MySQL/Qdrant/MinIO 实现。
    """

    def __init__(
        self,
        *,
        skill_catalog_path: Path | None = None,
        state_catalog_path: Path | None = None,
    ) -> None:
        self.videos: dict[UUID, Video] = {}
        self.timeline: dict[UUID, list[TimelineArtifact]] = {}
        self.questions: dict[UUID, Question] = {}
        self.answers: dict[UUID, Answer] = {}
        self.runs: dict[UUID, RunRecord] = {}
        self.processing_runs: dict[UUID, ProcessingRun] = {}
        self.semantic_events: dict[UUID, list[SemanticEvent]] = {}
        self.narrative_contexts: dict[UUID, NarrativeContext] = {}
        self.trace_events: dict[UUID, list[TraceEvent]] = {}
        self.usage_events: list[UsageEvent] = []
        self.skills: dict[UUID, Skill] = {}
        self.skill_versions: dict[UUID, list[SkillVersion]] = {}
        self.skill_bindings: dict[UUID, SkillBinding] = {}
        self._skill_catalog_path = skill_catalog_path
        self._state_catalog_path = state_catalog_path
        self._lock = asyncio.Lock()
        self._load_state_catalog()
        self._load_skill_catalog()

    async def add(self, video: Video) -> None:
        async with self._lock:
            self.videos[video.id] = video.model_copy(deep=True)
            self._persist_state_catalog()

    async def get(self, video_id: UUID) -> Video | None:
        video = self.videos.get(video_id)
        return video.model_copy(deep=True) if video else None

    async def list(self) -> Sequence[Video]:
        return [
            item.model_copy(deep=True)
            for item in sorted(
                self.videos.values(),
                key=lambda video: video.created_at,
                reverse=True,
            )
        ]

    async def update(self, video: Video) -> None:
        async with self._lock:
            if video.id not in self.videos:
                raise KeyError(f"video not found: {video.id}")
            self.videos[video.id] = video.model_copy(deep=True)
            self._persist_state_catalog()

    async def delete(self, video_id: UUID) -> None:
        async with self._lock:
            self.videos.pop(video_id, None)
            self.timeline.pop(video_id, None)
            self.processing_runs.pop(video_id, None)
            self.semantic_events.pop(video_id, None)
            self.narrative_contexts.pop(video_id, None)
            self.skill_bindings.pop(video_id, None)
            self._persist_state_catalog()
            self._persist_skill_catalog()

    async def add_many(self, artifacts: Sequence[TimelineArtifact]) -> None:
        async with self._lock:
            for artifact in artifacts:
                bucket = self.timeline.setdefault(artifact.video_id, [])
                bucket.append(artifact.model_copy(deep=True))
                bucket.sort(key=lambda item: (item.time_range.start_ms, item.kind.value))
            self._persist_state_catalog()

    async def list_for_video(self, video_id: UUID) -> Sequence[TimelineArtifact]:
        return [item.model_copy(deep=True) for item in self.timeline.get(video_id, [])]

    async def add_question(self, question: Question) -> None:
        async with self._lock:
            self.questions[question.id] = question.model_copy(deep=True)

    async def add_answer(self, answer: Answer) -> None:
        async with self._lock:
            self.answers[answer.id] = answer.model_copy(deep=True)

    async def get_answer(self, answer_id: UUID) -> Answer | None:
        answer = self.answers.get(answer_id)
        return answer.model_copy(deep=True) if answer else None

    async def add_run(self, run: RunRecord) -> None:
        run_id = run.id
        async with self._lock:
            self.runs[run_id] = run

    async def update_run(self, run: RunRecord) -> None:
        await self.add_run(run)

    async def get_run(self, run_id: UUID) -> RunRecord | None:
        return self.runs.get(run_id)

    async def upsert_processing_run(self, run: ProcessingRun) -> None:
        async with self._lock:
            self.processing_runs[run.video_id] = run.model_copy(deep=True)
            self._persist_state_catalog()

    async def get_processing_run(self, video_id: UUID) -> ProcessingRun | None:
        run = self.processing_runs.get(video_id)
        return run.model_copy(deep=True) if run else None

    async def replace_semantic_events(
        self, video_id: UUID, events: Sequence[SemanticEvent]
    ) -> None:
        async with self._lock:
            self.semantic_events[video_id] = sorted(
                (event.model_copy(deep=True) for event in events),
                key=lambda item: item.time_range.start_ms,
            )
            self._persist_state_catalog()

    async def list_semantic_events(self, video_id: UUID) -> Sequence[SemanticEvent]:
        return [item.model_copy(deep=True) for item in self.semantic_events.get(video_id, [])]

    async def upsert_narrative_context(self, context: NarrativeContext) -> None:
        async with self._lock:
            self.narrative_contexts[context.video_id] = context.model_copy(deep=True)
            self._persist_state_catalog()

    async def get_narrative_context(self, video_id: UUID) -> NarrativeContext | None:
        context = self.narrative_contexts.get(video_id)
        return context.model_copy(deep=True) if context else None

    async def append_trace_event(self, event: TraceEvent) -> None:
        async with self._lock:
            bucket = self.trace_events.setdefault(event.trace_id, [])
            bucket[:] = [item for item in bucket if item.id != event.id]
            bucket.append(event.model_copy(deep=True))
            bucket.sort(key=lambda item: (item.sequence, item.occurred_at))

    async def list_trace_events(self, trace_id: UUID) -> Sequence[TraceEvent]:
        return [item.model_copy(deep=True) for item in self.trace_events.get(trace_id, [])]

    async def append_usage_event(self, event: UsageEvent) -> None:
        async with self._lock:
            self.usage_events[:] = [item for item in self.usage_events if item.id != event.id]
            self.usage_events.append(event.model_copy(deep=True))

    async def list_usage_events(self, video_id: UUID | None = None) -> Sequence[UsageEvent]:
        events = self.usage_events
        if video_id is not None:
            events = [item for item in events if item.video_id == video_id]
        return [item.model_copy(deep=True) for item in events]

    async def upsert_skill(self, skill: Skill) -> None:
        async with self._lock:
            self.skills[skill.id] = skill.model_copy(deep=True)
            self._persist_skill_catalog()

    async def get_skill(self, skill_id: UUID) -> Skill | None:
        skill = self.skills.get(skill_id)
        return skill.model_copy(deep=True) if skill else None

    async def list_skills(self) -> Sequence[Skill]:
        return [
            item.model_copy(deep=True)
            for item in sorted(
                self.skills.values(), key=lambda value: value.updated_at, reverse=True
            )
        ]

    async def add_skill_version(self, version: SkillVersion) -> None:
        async with self._lock:
            bucket = self.skill_versions.setdefault(version.skill_id, [])
            bucket[:] = [item for item in bucket if item.version != version.version]
            bucket.append(version.model_copy(deep=True))
            bucket.sort(key=lambda item: item.version)
            self._persist_skill_catalog()

    async def get_skill_version(self, skill_id: UUID, version: int) -> SkillVersion | None:
        item = next(
            (item for item in self.skill_versions.get(skill_id, []) if item.version == version),
            None,
        )
        return item.model_copy(deep=True) if item else None

    async def list_skill_versions(self, skill_id: UUID) -> Sequence[SkillVersion]:
        return [item.model_copy(deep=True) for item in self.skill_versions.get(skill_id, [])]

    async def upsert_skill_binding(self, binding: SkillBinding) -> None:
        async with self._lock:
            self.skill_bindings[binding.video_id] = binding.model_copy(deep=True)
            self._persist_skill_catalog()

    async def delete_skill_binding(self, video_id: UUID) -> None:
        async with self._lock:
            self.skill_bindings.pop(video_id, None)
            self._persist_skill_catalog()

    async def get_skill_binding(self, video_id: UUID) -> SkillBinding | None:
        binding = self.skill_bindings.get(video_id)
        return binding.model_copy(deep=True) if binding else None

    async def list_skill_bindings(self, skill_id: UUID | None = None) -> Sequence[SkillBinding]:
        items = list(self.skill_bindings.values())
        if skill_id is not None:
            items = [item for item in items if item.skill_id == skill_id]
        return [item.model_copy(deep=True) for item in items]

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def _load_state_catalog(self) -> None:
        """恢复本地视频、时间轴和处理结果，使 videos/ 真正成为可复用视频库。"""

        path = self._state_catalog_path
        if path is None or not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for raw in payload.get("videos", []):
                video = Video.model_validate(raw)
                self.videos[video.id] = video
            for raw in payload.get("timeline", []):
                artifact = TimelineArtifact.model_validate(raw)
                self.timeline.setdefault(artifact.video_id, []).append(artifact)
            for items in self.timeline.values():
                items.sort(key=lambda item: (item.time_range.start_ms, item.kind.value))
            for raw in payload.get("processing_runs", []):
                run = ProcessingRun.model_validate(raw)
                if run.status in {ProcessingStatus.QUEUED, ProcessingStatus.RUNNING}:
                    run.status = ProcessingStatus.FAILED
                    run.error = "服务曾在任务运行时退出，请点击重新处理以从缓存继续。"
                    run.finished_at = utc_now()
                    restored_video = self.videos.get(run.video_id)
                    if restored_video is not None:
                        restored_video.status = VideoStatus.FAILED
                        restored_video.current_stage = "interrupted"
                        restored_video.error_message = run.error
                self.processing_runs[run.video_id] = run
            for raw in payload.get("semantic_events", []):
                event = SemanticEvent.model_validate(raw)
                self.semantic_events.setdefault(event.video_id, []).append(event)
            for raw in payload.get("narrative_contexts", []):
                context = NarrativeContext.model_validate(raw)
                self.narrative_contexts[context.video_id] = context
        except (OSError, ValueError, TypeError):
            self.videos.clear()
            self.timeline.clear()
            self.processing_runs.clear()
            self.semantic_events.clear()
            self.narrative_contexts.clear()

    def _persist_state_catalog(self) -> None:
        path = self._state_catalog_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "videos": [item.model_dump(mode="json") for item in self.videos.values()],
            "timeline": [
                item.model_dump(mode="json")
                for artifacts in self.timeline.values()
                for item in artifacts
            ],
            "processing_runs": [
                item.model_dump(mode="json") for item in self.processing_runs.values()
            ],
            "semantic_events": [
                item.model_dump(mode="json")
                for events in self.semantic_events.values()
                for item in events
            ],
            "narrative_contexts": [
                item.model_dump(mode="json") for item in self.narrative_contexts.values()
            ],
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _load_skill_catalog(self) -> None:
        """开发态也持久化 Skill，避免每次重启都丢失人工审核结果。"""

        path = self._skill_catalog_path
        if path is None or not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for raw in payload.get("skills", []):
                skill = Skill.model_validate(raw)
                self.skills[skill.id] = skill
            for raw in payload.get("versions", []):
                version = SkillVersion.model_validate(raw)
                self.skill_versions.setdefault(version.skill_id, []).append(version)
            for items in self.skill_versions.values():
                items.sort(key=lambda value: value.version)
            for raw in payload.get("bindings", []):
                binding = SkillBinding.model_validate(raw)
                self.skill_bindings[binding.video_id] = binding
        except (OSError, ValueError, TypeError):
            # 损坏的开发态目录不能阻止 API 启动；后续写入会生成新的合法快照。
            self.skills.clear()
            self.skill_versions.clear()
            self.skill_bindings.clear()

    def _persist_skill_catalog(self) -> None:
        path = self._skill_catalog_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "skills": [item.model_dump(mode="json") for item in self.skills.values()],
            "versions": [
                item.model_dump(mode="json")
                for versions in self.skill_versions.values()
                for item in versions
            ],
            "bindings": [item.model_dump(mode="json") for item in self.skill_bindings.values()],
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def _target_window(target: QuestionTarget) -> tuple[int, int] | None:
    if isinstance(target, GlobalTarget):
        return None
    if isinstance(target, RangeTarget):
        return target.time_range.start_ms, target.time_range.end_ms
    if isinstance(target, MomentTarget):
        half = target.context_window_ms
        return max(0, target.timestamp_ms - half), target.timestamp_ms + half
    if isinstance(target, FrameTarget):
        return max(0, target.timestamp_ms - 2_500), target.timestamp_ms + 2_500
    return None


def _kind_to_evidence(kind: TimelineKind) -> EvidenceKind:
    if kind in {TimelineKind.TRANSCRIPT, TimelineKind.SPEAKER_TURN}:
        return EvidenceKind.TRANSCRIPT
    if kind is TimelineKind.OCR:
        return EvidenceKind.OCR
    if kind in {TimelineKind.VISUAL, TimelineKind.KEYFRAME, TimelineKind.SHOT}:
        return EvidenceKind.VISUAL
    return EvidenceKind.TIMELINE


class InMemoryRetrieval:
    def __init__(self, store: TimelineRepository, api_prefix: str = "/api/v1") -> None:
        self._store = store
        self._api_prefix = api_prefix

    async def search(
        self,
        *,
        video_id: UUID,
        query: str,
        target: QuestionTarget,
        limit: int,
    ) -> Sequence[Evidence]:
        artifacts = await self._store.list_for_video(video_id)
        window = _target_window(target)
        query_chars = {char for char in query.lower() if not char.isspace()}

        if window is None and _is_global_summary_query(query):
            return self._summary_evidence(list(artifacts), limit)

        candidates: list[tuple[float, TimelineArtifact]] = []
        for artifact in artifacts:
            if window is not None:
                start_ms, end_ms = window
                if artifact.time_range.end_ms < start_ms or artifact.time_range.start_ms > end_ms:
                    continue

            searchable = f"{artifact.title or ''}{artifact.text}{' '.join(artifact.tags)}".lower()
            overlap = sum(1 for char in query_chars if char in searchable)
            # 全局问题优先章节；局部问题优先时间锚点附近的直接观察。
            kind_bonus = 4 if window is None and artifact.kind is TimelineKind.CHAPTER else 0
            score = overlap + kind_bonus + artifact.confidence
            candidates.append((score, artifact))

        candidates.sort(
            key=lambda item: (-item[0], item[1].time_range.start_ms, item[1].kind.value)
        )
        return [self._to_evidence(artifact) for _, artifact in candidates[:limit]]

    def _summary_evidence(self, artifacts: list[TimelineArtifact], limit: int) -> list[Evidence]:
        """为全片总结按时间均匀聚合证据，避免关键词检索只命中开头和结尾。"""
        chapters = [item for item in artifacts if item.kind is TimelineKind.CHAPTER]
        transcripts = [
            item
            for item in artifacts
            if item.kind in {TimelineKind.TRANSCRIPT, TimelineKind.SPEAKER_TURN}
        ]
        if chapters:
            # 章节标题只能说明“这一段叫什么”，不能支撑专业总结。将每章内的完整字幕
            # 聚合到同一条证据里，让模型真正看到每条建议的论据、例子和专业名词。
            semantic = self._aggregate_transcript_by_chapters(chapters, transcripts)
            if not semantic:
                # 合成测试或外部索引可能只有章节而没有逐句字幕，仍保留章节级证据。
                semantic = [self._to_evidence(item) for item in chapters[: max(1, limit - 3)]]
        else:
            semantic = self._aggregate_transcript_windows(
                transcripts,
                bucket_count=min(10, max(4, limit - 4)),
            )
        visuals = [
            item for item in artifacts if item.kind in {TimelineKind.VISUAL, TimelineKind.OCR}
        ]
        visuals.sort(key=lambda item: item.time_range.start_ms)
        slots = max(0, limit - len(semantic))
        sampled = _evenly_sample(visuals, min(slots, 4))
        return [*semantic, *(self._to_evidence(item) for item in sampled)][:limit]

    def _aggregate_transcript_by_chapters(
        self,
        chapters: list[TimelineArtifact],
        transcripts: list[TimelineArtifact],
    ) -> list[Evidence]:
        result: list[Evidence] = []
        for chapter in chapters:
            items = [
                item
                for item in transcripts
                if chapter.time_range.start_ms
                <= item.time_range.start_ms
                < chapter.time_range.end_ms
            ]
            if not items:
                result.append(self._to_evidence(chapter))
                continue
            spoken = " ".join(item.text.strip() for item in items if item.text.strip())
            text = f"章节：{chapter.text}。本章字幕：{spoken}"[:3600]
            result.append(
                Evidence(
                    video_id=chapter.video_id,
                    kind=EvidenceKind.TRANSCRIPT,
                    artifact_ids=[chapter.id, *(item.id for item in items)],
                    time_range=chapter.time_range,
                    timestamp_ms=chapter.time_range.start_ms,
                    quote=text,
                    description=text,
                    confidence=sum(item.confidence for item in items) / len(items),
                    provenance=items[0].provenance,
                )
            )
        return result

    def _aggregate_transcript_windows(
        self, transcripts: list[TimelineArtifact], bucket_count: int
    ) -> list[Evidence]:
        if not transcripts:
            return []
        duration = max(item.time_range.end_ms for item in transcripts)
        window_size = max(1, (duration + bucket_count - 1) // bucket_count)
        result: list[Evidence] = []
        for start_ms in range(0, duration, window_size):
            items = [
                item
                for item in transcripts
                if start_ms <= item.time_range.start_ms < start_ms + window_size
            ]
            if not items:
                continue
            text = " ".join(item.text.strip() for item in items if item.text.strip())[:2400]
            if not text:
                continue
            result.append(
                Evidence(
                    video_id=items[0].video_id,
                    kind=EvidenceKind.TRANSCRIPT,
                    artifact_ids=[item.id for item in items],
                    time_range=TimeRange(
                        start_ms=items[0].time_range.start_ms,
                        end_ms=items[-1].time_range.end_ms,
                    ),
                    timestamp_ms=items[0].time_range.start_ms,
                    quote=text,
                    description=text,
                    confidence=sum(item.confidence for item in items) / len(items),
                    provenance=items[0].provenance,
                )
            )
        return result

    def _to_evidence(self, artifact: TimelineArtifact) -> Evidence:
        midpoint = (artifact.time_range.start_ms + artifact.time_range.end_ms) // 2
        anchor = midpoint
        is_quote = artifact.kind in {
            TimelineKind.TRANSCRIPT,
            TimelineKind.SPEAKER_TURN,
            TimelineKind.OCR,
        }
        snapshot_url = None
        if artifact.snapshot_key:
            if artifact.snapshot_key.startswith("frames/"):
                parts = artifact.snapshot_key.split("/")
                snapshot_url = f"{self._api_prefix}/videos/{parts[1]}/frames/{parts[2]}"
                # 帧文件名就是采样时间戳；引用必须与截图一致，不能使用 OCR 区间中点。
                try:
                    anchor = int(parts[2].split(".", maxsplit=1)[0])
                except (ValueError, IndexError):
                    anchor = midpoint
            else:
                snapshot_url = (
                    f"{self._api_prefix}/demo/frames/{midpoint}.svg?label={artifact.snapshot_key}"
                )
        return Evidence(
            video_id=artifact.video_id,
            kind=_kind_to_evidence(artifact.kind),
            artifact_ids=[artifact.id],
            time_range=artifact.time_range,
            timestamp_ms=anchor,
            spatial_region=artifact.spatial_region,
            quote=artifact.text if is_quote else None,
            description=artifact.text,
            confidence=artifact.confidence,
            snapshot_url=snapshot_url,
            provenance=artifact.provenance,
        )


class InMemoryFrameInspector:
    """开发态帧检查器。

    真正部署时，此 Port 会调用 FFmpeg 按 PTS 抽帧，再把图像交给 OCR/VLM。当前实现
    返回指定时刻附近已经生成的视觉与 OCR 证据，使 Agent 流程可离线、可重复测试。
    """

    def __init__(
        self,
        retrieval: InMemoryRetrieval,
        *,
        store: Any | None = None,
        data_dir: Path | None = None,
        library_dir: Path | None = None,
        vlm: Any | None = None,
        vlm_timeout_seconds: float = 45,
    ) -> None:
        self._retrieval = retrieval
        self._store = store
        self._data_dir = data_dir.resolve() if data_dir else None
        self._library_dir = (library_dir or data_dir).resolve() if data_dir else None
        self._vlm = vlm
        self._vlm_timeout_seconds = vlm_timeout_seconds

    async def inspect(
        self,
        *,
        video_id: UUID,
        timestamp_ms: int,
        query: str,
    ) -> Sequence[Evidence]:
        # 当前帧问答必须分析用户指定时间的真实图片，不能把附近旧证据改写成当前时间。
        if self._store and self._data_dir and self._library_dir and self._vlm:
            video = await self._store.get(video_id)
            if video and video.source_object_key:
                source = resolve_video_source(
                    object_key=video.source_object_key,
                    data_dir=self._data_dir,
                    library_dir=self._library_dir,
                )
                if source.exists():
                    from lets_go_video_agent.media.local_pipeline import extract_frame_at

                    frame_dir = self._data_dir / "frames-on-demand" / str(video_id)
                    frame_dir.mkdir(parents=True, exist_ok=True)
                    frame_path = frame_dir / f"{timestamp_ms:010d}.jpg"
                    if not frame_path.exists():
                        await extract_frame_at(source, frame_path, timestamp_ms)
                    try:
                        observations = await asyncio.wait_for(
                            self._vlm.analyze_frames(
                                [{"path": frame_path, "timestamp_ms": timestamp_ms}],
                                video_id=str(video_id),
                                question=query,
                            ),
                            timeout=self._vlm_timeout_seconds,
                        )
                    except Exception:
                        # 云端 VLM 超时或网络波动不能让问答接口崩溃；降级时仍只分析
                        # 同一张精确帧，绝不拿附近的旧截图冒充当前画面。
                        from lets_go_video_agent.media.local_pipeline import run_ocr

                        ocr_cache = frame_dir / f"{timestamp_ms:010d}.ocr.json"
                        ocr_items = await asyncio.to_thread(
                            run_ocr,
                            [{"path": frame_path, "timestamp_ms": timestamp_ms}],
                            ocr_cache,
                        )
                        visible_text = " / ".join(
                            str(item.get("text") or "").strip()
                            for item in ocr_items
                            if str(item.get("text") or "").strip()
                        )
                        return [
                            Evidence(
                                video_id=video_id,
                                kind=EvidenceKind.FRAME,
                                timestamp_ms=timestamp_ms,
                                quote=visible_text or None,
                                description=(
                                    f"当前精确帧可见文字：{visible_text}"
                                    if visible_text
                                    else "已取得当前精确帧，但视觉模型暂时不可连接。"
                                ),
                                confidence=0.72 if visible_text else 0.2,
                                snapshot_url=(
                                    f"/api/v1/videos/{video_id}/frame-at/{timestamp_ms}.jpg"
                                ),
                                provenance=Provenance(
                                    producer="exact-frame-ocr-fallback",
                                    tool_version="network-safe-v1",
                                ),
                            )
                        ]
                    if observations:
                        observation = observations[0]
                        description = "；".join(
                            part
                            for part in (
                                str(observation.get("scene") or "").strip(),
                                str(observation.get("meaning") or "").strip(),
                                "、".join(str(x) for x in observation.get("actions", [])),
                            )
                            if part
                        )
                        return [
                            Evidence(
                                video_id=video_id,
                                kind=EvidenceKind.FRAME,
                                timestamp_ms=timestamp_ms,
                                description=description or "VLM 未返回可靠的画面语义描述",
                                confidence=float(observation.get("importance") or 0.8),
                                snapshot_url=(
                                    f"/api/v1/videos/{video_id}/frame-at/{timestamp_ms}.jpg"
                                ),
                                provenance=Provenance(
                                    producer="on-demand-frame-vlm",
                                    model=getattr(self._vlm, "model", None),
                                    prompt_version="exact-frame-question-v1",
                                ),
                            )
                        ]
                    # 已成功抽取精确帧但 VLM 无结果时宁可返回无证据，也不能降级成邻近旧帧。
                    return []

        target = FrameTarget(timestamp_ms=timestamp_ms)
        evidence = await self._retrieval.search(
            video_id=video_id,
            query=query,
            target=target,
            limit=6,
        )
        visual = [
            item
            for item in evidence
            if item.kind in {EvidenceKind.VISUAL, EvidenceKind.OCR, EvidenceKind.FRAME}
        ]
        # “当前帧”必须锚定用户指定时刻，而不是复用 OCR 区间中点或最后一张采样图。
        exact_snapshot = f"/api/v1/videos/{video_id}/frame-at/{timestamp_ms}.jpg"
        result: list[Evidence] = []
        seen_quotes: set[str] = set()
        for item in visual:
            signature = (item.quote or item.description).strip()
            if signature in seen_quotes:
                continue
            seen_quotes.add(signature)
            result.append(
                item.model_copy(
                    update={"timestamp_ms": timestamp_ms, "snapshot_url": exact_snapshot}
                )
            )
        return result[:3]


def _is_global_summary_query(query: str) -> bool:
    normalized = query.lower().replace(" ", "")
    return any(marker in normalized for marker in ("总结", "概括", "主要内容", "讲了什么", "大意"))


def _evenly_sample(items: list[TimelineArtifact], count: int) -> list[TimelineArtifact]:
    if count <= 0 or not items:
        return []
    if len(items) <= count:
        return items
    if count == 1:
        return [items[len(items) // 2]]
    return [items[round(index * (len(items) - 1) / (count - 1))] for index in range(count)]
