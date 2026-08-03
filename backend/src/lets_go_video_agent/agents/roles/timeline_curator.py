from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from lets_go_video_agent.domain.common import Provenance, TimeRange
from lets_go_video_agent.domain.timeline import ObservationType, TimelineArtifact, TimelineKind
from lets_go_video_agent.domain.video import Video


class TimelineCurator:
    """把多轨原始结果整理成语义章节，同时保留原轨道。"""

    name = "timeline_curator"
    version = "0.1.0"

    def curate(
        self,
        *,
        video: Video,
        artifacts: Sequence[TimelineArtifact],
    ) -> list[TimelineArtifact]:
        existing = [item for item in artifacts if item.kind is TimelineKind.CHAPTER]
        if existing:
            return sorted(existing, key=lambda item: item.time_range.start_ms)

        # P0 的离线回退按一分钟桶生成章节；真实 Agent 会融合语义突变、镜头边界、
        # 话题变化和 OCR 状态。回退策略保证模型不可用时仍能得到完整时间覆盖。
        buckets: dict[int, list[TimelineArtifact]] = defaultdict(list)
        for artifact in artifacts:
            buckets[artifact.time_range.start_ms // 60_000].append(artifact)

        chapters: list[TimelineArtifact] = []
        duration_ms = video.duration_ms or max(
            (item.time_range.end_ms for item in artifacts),
            default=1,
        )
        for bucket_index, items in sorted(buckets.items()):
            start_ms = bucket_index * 60_000
            end_ms = min(duration_ms, max(start_ms + 1, (bucket_index + 1) * 60_000))
            snippets = [item.text.strip() for item in items if item.text.strip()]
            summary = "；".join(snippets[:3]) or "该片段暂无可用文字描述"
            chapters.append(
                TimelineArtifact(
                    video_id=video.id,
                    kind=TimelineKind.CHAPTER,
                    time_range=TimeRange(start_ms=start_ms, end_ms=end_ms),
                    title=f"自动章节 {bucket_index + 1}",
                    text=summary[:240],
                    confidence=0.55,
                    observation_type=ObservationType.INFERENCE,
                    provenance=Provenance(
                        producer=self.name,
                        producer_version=self.version,
                        prompt_version="fallback-bucket-v1",
                    ),
                )
            )
        return chapters
