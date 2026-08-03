from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import UUID

from lets_go_video_agent.application.ports import RunRecord, TimelineRepository
from lets_go_video_agent.domain.common import TimeRange
from lets_go_video_agent.domain.qa import (
    Answer,
    FrameTarget,
    GlobalTarget,
    MomentTarget,
    Question,
    QuestionTarget,
    RangeTarget,
)
from lets_go_video_agent.domain.timeline import (
    Evidence,
    EvidenceKind,
    TimelineArtifact,
    TimelineKind,
)
from lets_go_video_agent.domain.video import Video


class InMemoryStore:
    """开发态仓库，同时实现多个 Port。

    这是一个可替换适配器，不是“临时绕过架构”的全局字典。应用层只依赖 Port，
    Docker 模式会在装配点换成 MySQL/Qdrant/MinIO 实现。
    """

    def __init__(self) -> None:
        self.videos: dict[UUID, Video] = {}
        self.timeline: dict[UUID, list[TimelineArtifact]] = {}
        self.questions: dict[UUID, Question] = {}
        self.answers: dict[UUID, Answer] = {}
        self.runs: dict[UUID, RunRecord] = {}
        self._lock = asyncio.Lock()

    async def add(self, video: Video) -> None:
        async with self._lock:
            self.videos[video.id] = video.model_copy(deep=True)

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

    async def add_many(self, artifacts: Sequence[TimelineArtifact]) -> None:
        async with self._lock:
            for artifact in artifacts:
                bucket = self.timeline.setdefault(artifact.video_id, [])
                bucket.append(artifact.model_copy(deep=True))
                bucket.sort(key=lambda item: (item.time_range.start_ms, item.kind.value))

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

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


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

    def _summary_evidence(
        self, artifacts: list[TimelineArtifact], limit: int
    ) -> list[Evidence]:
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
                semantic = [
                    self._to_evidence(item) for item in chapters[: max(1, limit - 3)]
                ]
        else:
            semantic = self._aggregate_transcript_windows(
                transcripts,
                bucket_count=min(10, max(4, limit - 4)),
            )
        visuals = [
            item
            for item in artifacts
            if item.kind in {TimelineKind.VISUAL, TimelineKind.OCR}
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
                if chapter.time_range.start_ms <= item.time_range.start_ms
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

    def __init__(self, retrieval: InMemoryRetrieval) -> None:
        self._retrieval = retrieval

    async def inspect(
        self,
        *,
        video_id: UUID,
        timestamp_ms: int,
        query: str,
    ) -> Sequence[Evidence]:
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
