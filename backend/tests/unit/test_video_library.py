from pathlib import Path

import pytest

from lets_go_video_agent.domain.common import Provenance, TimeRange
from lets_go_video_agent.domain.timeline import TimelineArtifact, TimelineKind
from lets_go_video_agent.domain.video import VideoStatus
from lets_go_video_agent.infrastructure.memory import InMemoryStore
from lets_go_video_agent.media.video_library import (
    resolve_video_source,
    sync_video_library,
)


@pytest.mark.asyncio
async def test_local_video_library_is_idempotent_and_restores_results(tmp_path: Path) -> None:
    library = tmp_path / "videos"
    library.mkdir()
    media = library / "sample.mp4"
    media.write_bytes(b"synthetic-test-media")
    state = tmp_path / "data" / "catalog" / "memory-state.json"
    store = InMemoryStore(state_catalog_path=state)

    first = await sync_video_library(store, library)
    second = await sync_video_library(store, library)

    assert len(first) == 1
    assert second == []
    video = first[0]
    assert video.source_object_key == "library/sample.mp4"
    assert (
        resolve_video_source(
            object_key=video.source_object_key,
            data_dir=tmp_path / "data",
            library_dir=library,
        )
        == media
    )

    video.status = VideoStatus.READY
    video.duration_ms = 10_000
    await store.update(video)
    await store.add_many(
        [
            TimelineArtifact(
                video_id=video.id,
                kind=TimelineKind.CHAPTER,
                time_range=TimeRange(start_ms=0, end_ms=10_000),
                title="测试章节",
                text="持久化后的理解结果",
                confidence=1,
                provenance=Provenance(producer="test"),
            )
        ]
    )

    restored = InMemoryStore(state_catalog_path=state)
    await sync_video_library(restored, library)
    restored_videos = list(await restored.list())
    assert len(restored_videos) == 1
    assert restored_videos[0].status == VideoStatus.READY
    assert len(await restored.list_for_video(video.id)) == 1
