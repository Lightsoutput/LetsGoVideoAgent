from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel
from lets_go_video_agent.domain.video import Video


class ProcessingProfile(StrEnum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    HIGH_ACCURACY = "high_accuracy"


class ProcessingStep(DomainModel):
    name: str
    worker: str
    required: bool = True
    parameters: dict[str, object] = Field(default_factory=dict)


class ProcessingPlan(DomainModel):
    profile: ProcessingProfile
    steps: list[ProcessingStep]
    estimated_visual_calls: int = Field(ge=0)
    rationale: list[str]


class ProcessingPlanner:
    """根据媒体特征制定处理策略，不直接执行下载或 FFmpeg。"""

    name = "processing_planner"
    version = "0.1.0"

    def plan(
        self,
        video: Video,
        profile: ProcessingProfile = ProcessingProfile.BALANCED,
    ) -> ProcessingPlan:
        duration_seconds = (video.duration_ms or 0) / 1_000
        interval = {
            ProcessingProfile.ECONOMY: 12,
            ProcessingProfile.BALANCED: 6,
            ProcessingProfile.HIGH_ACCURACY: 3,
        }[profile]
        estimated_visual_calls = max(1, int(duration_seconds / interval)) if duration_seconds else 1
        steps = [
            ProcessingStep(name="probe", worker="media", parameters={"tool": "ffprobe"}),
            ProcessingStep(name="extract_audio", worker="media", parameters={"codec": "wav"}),
            ProcessingStep(name="scene_detection", worker="media", parameters={"adaptive": True}),
            ProcessingStep(
                name="keyframes",
                worker="media",
                parameters={"max_interval_seconds": interval},
            ),
            ProcessingStep(name="asr", worker="model", parameters={"speaker_labels": True}),
            ProcessingStep(name="ocr", worker="model", parameters={"keyframes_only": True}),
            ProcessingStep(
                name="visual_understanding",
                worker="model",
                parameters={"on_demand": profile is ProcessingProfile.ECONOMY},
            ),
            ProcessingStep(name="timeline_curate", worker="agent"),
            ProcessingStep(name="index", worker="retrieval"),
        ]
        return ProcessingPlan(
            profile=profile,
            steps=steps,
            estimated_visual_calls=estimated_visual_calls,
            rationale=[
                "先做镜头检测和低成本 OCR，再选择需要视觉模型分析的关键帧。",
                "不逐帧调用 VLM；经济模式把深度视觉理解延迟到用户提问时。",
                "下载、转码和模型推理均由 Worker 执行，Agent 只输出计划。",
            ],
        )
