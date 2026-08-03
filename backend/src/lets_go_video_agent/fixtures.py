from __future__ import annotations

from uuid import UUID

from lets_go_video_agent.application.ports import AppStore
from lets_go_video_agent.domain.common import Provenance, SpatialRegion, TimeRange
from lets_go_video_agent.domain.timeline import ObservationType, TimelineArtifact, TimelineKind
from lets_go_video_agent.domain.video import SyntheticSource, Video, VideoStatus

DEMO_VIDEO_ID = UUID("11111111-1111-4111-8111-111111111111")


async def seed_demo(store: AppStore) -> None:
    """写入不含第三方媒体的合成知识夹具，用于端到端验证 UI 和 Agent。"""

    if await store.get(DEMO_VIDEO_ID):
        return

    video = Video(
        id=DEMO_VIDEO_ID,
        title="合成演示：塔防游戏新手关卡讲解",
        source=SyntheticSource(fixture_name="tower-defense-tutorial-v1"),
        status=VideoStatus.READY,
        duration_ms=300_000,
        width=1920,
        height=1080,
        fps=30,
        progress=1,
        current_stage="ready",
        metadata={
            "fixture": True,
            "notice": "所有文字与画面描述均为项目自制测试内容",
        },
    )
    await store.add(video)

    worker = Provenance(producer="synthetic-fixture", tool_version="1.0")
    curator = Provenance(
        producer="timeline_curator",
        prompt_version="general-video-v1",
        model="mock-curator",
    )
    artifacts = [
        TimelineArtifact(
            video_id=video.id,
            kind=TimelineKind.CHAPTER,
            time_range=TimeRange(start_ms=0, end_ms=58_000),
            title="任务目标与规则",
            text="介绍本次关卡目标、失败条件和需要保护的终点。",
            confidence=0.96,
            observation_type=ObservationType.INFERENCE,
            provenance=curator,
        ),
        TimelineArtifact(
            video_id=video.id,
            kind=TimelineKind.TRANSCRIPT,
            time_range=TimeRange(start_ms=11_000, end_ms=27_000),
            text="这一关先不要急着部署输出角色，第一波需要先建立资源循环。",
            speaker="Speaker 1",
            confidence=0.93,
            provenance=worker,
        ),
        TimelineArtifact(
            video_id=video.id,
            kind=TimelineKind.CHAPTER,
            time_range=TimeRange(start_ms=58_000, end_ms=142_000),
            title="阵容与部署顺序",
            text="展示编队界面，解释先部署资源角色，再补治疗和防御角色。",
            confidence=0.95,
            observation_type=ObservationType.INFERENCE,
            provenance=curator,
        ),
        TimelineArtifact(
            video_id=video.id,
            kind=TimelineKind.VISUAL,
            time_range=TimeRange(start_ms=67_000, end_ms=76_000),
            title="编队界面",
            text="画面为角色编队页，三个职业筛选按钮被依次高亮，右侧显示队伍空位。",
            confidence=0.91,
            snapshot_key="formation-screen",
            provenance=worker,
        ),
        TimelineArtifact(
            video_id=video.id,
            kind=TimelineKind.OCR,
            time_range=TimeRange(start_ms=68_000, end_ms=75_000),
            text="资源 / 治疗 / 防御",
            confidence=0.89,
            spatial_region=SpatialRegion(x=0.08, y=0.17, width=0.34, height=0.16),
            snapshot_key="formation-ocr",
            provenance=worker,
        ),
        TimelineArtifact(
            video_id=video.id,
            kind=TimelineKind.TRANSCRIPT,
            time_range=TimeRange(start_ms=82_000, end_ms=103_000),
            text="推荐顺序是先放两名资源角色，费用稳定后在高台补一名治疗。",
            speaker="Speaker 1",
            confidence=0.94,
            provenance=worker,
        ),
        TimelineArtifact(
            video_id=video.id,
            kind=TimelineKind.CHAPTER,
            time_range=TimeRange(start_ms=142_000, end_ms=236_000),
            title="实战与失误修正",
            text="进入实战，演示敌人路线，并在漏怪后回退解释防御角色朝向。",
            confidence=0.92,
            observation_type=ObservationType.INFERENCE,
            provenance=curator,
        ),
        TimelineArtifact(
            video_id=video.id,
            kind=TimelineKind.EVENT,
            time_range=TimeRange(start_ms=178_000, end_ms=193_000),
            title="第一次漏怪",
            text="一名敌人穿过左路防线，随后暂停并调整防御角色朝向。",
            confidence=0.87,
            snapshot_key="battle-correction",
            provenance=worker,
        ),
        TimelineArtifact(
            video_id=video.id,
            kind=TimelineKind.TRANSCRIPT,
            time_range=TimeRange(start_ms=187_000, end_ms=205_000),
            text="这里是常见失误，防御角色应该朝左，才能覆盖刚才漏掉的路线。",
            speaker="Speaker 1",
            confidence=0.92,
            provenance=worker,
        ),
        TimelineArtifact(
            video_id=video.id,
            kind=TimelineKind.CHAPTER,
            time_range=TimeRange(start_ms=236_000, end_ms=300_000),
            title="总结与可替换方案",
            text="复盘部署顺序，并说明没有同名角色时可按职业职责替换。",
            confidence=0.94,
            observation_type=ObservationType.INFERENCE,
            provenance=curator,
        ),
    ]
    await store.add_many(artifacts)
