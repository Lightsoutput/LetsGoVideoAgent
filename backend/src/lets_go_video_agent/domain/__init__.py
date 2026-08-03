"""纯领域模型。

这一层故意不依赖 FastAPI、SQLAlchemy 或 LangGraph。框架升级时，视频、证据和问答
这些核心业务概念不应该随之变化。
"""

from lets_go_video_agent.domain.common import ModelUsage, Provenance, SpatialRegion, TimeRange
from lets_go_video_agent.domain.qa import Answer, Question
from lets_go_video_agent.domain.timeline import Evidence, TimelineArtifact
from lets_go_video_agent.domain.video import Video

__all__ = [
    "Answer",
    "Evidence",
    "ModelUsage",
    "Provenance",
    "Question",
    "SpatialRegion",
    "TimeRange",
    "TimelineArtifact",
    "Video",
]
