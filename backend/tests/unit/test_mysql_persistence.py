from lets_go_video_agent.domain.video import SyntheticSource, Video, VideoStatus
from lets_go_video_agent.infrastructure.persistence.mysql.models import Base
from lets_go_video_agent.infrastructure.persistence.mysql.repository import MySqlStore


def test_mysql_schema_contains_p0_source_of_truth_tables() -> None:
    """不依赖 Docker，也能防止迁移/ORM 重构时误删 P0 的核心事实表。"""

    assert set(Base.metadata.tables) == {
        "agent_runs",
        "answers",
        "questions",
        "timeline_artifacts",
        "videos",
    }


def test_video_row_payload_round_trips_domain_model() -> None:
    """JSON payload 必须保持完整领域对象，热字段只是索引投影而非第二份事实。"""

    video = Video(
        title="MySQL adapter contract fixture",
        source=SyntheticSource(fixture_name="mysql-round-trip"),
        status=VideoStatus.READY,
        duration_ms=42_000,
        progress=1,
    )

    row = MySqlStore._video_row(video)
    restored = Video.model_validate(row.payload)

    assert restored == video
    assert row.id == str(video.id)
    assert row.status == VideoStatus.READY
