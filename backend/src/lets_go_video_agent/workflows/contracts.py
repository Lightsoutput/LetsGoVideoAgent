from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProcessingRequest:
    """Workflow 输入只保留稳定标识，不传递数据库连接或大型媒体。"""

    video_id: str
    source_object_key: str
    profile: str = "economy"


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    video_id: str
    status: str
    stage: str
    probe: dict[str, object] = field(default_factory=dict)
    audio_object_key: str | None = None
    limitations: tuple[str, ...] = ()
