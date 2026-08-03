from uuid import uuid4

import pytest

from lets_go_video_agent.agents.roles.qa_investigator import _remove_low_value_meta
from lets_go_video_agent.domain.common import Provenance, TimeRange
from lets_go_video_agent.domain.qa import GlobalTarget
from lets_go_video_agent.domain.timeline import TimelineArtifact, TimelineKind
from lets_go_video_agent.infrastructure.memory import InMemoryRetrieval, InMemoryStore
from lets_go_video_agent.infrastructure.models.deepseek_client import _parse_json_object


@pytest.mark.asyncio
async def test_global_summary_retrieval_covers_entire_timeline() -> None:
    video_id = uuid4()
    store = InMemoryStore()
    await store.add_many(
        [
            TimelineArtifact(
                video_id=video_id,
                kind=TimelineKind.TRANSCRIPT,
                time_range=TimeRange(start_ms=index * 10_000, end_ms=index * 10_000 + 5_000),
                text=f"第 {index} 段的重要内容",
                confidence=0.9,
                provenance=Provenance(producer="test-asr"),
            )
            for index in range(24)
        ]
    )

    evidence = await InMemoryRetrieval(store).search(
        video_id=video_id,
        query="全面总结视频主要内容",
        target=GlobalTarget(),
        limit=10,
    )

    anchors = [item.timestamp_ms or 0 for item in evidence]
    assert len(evidence) >= 6
    assert min(anchors) < 30_000
    assert max(anchors) > 180_000
    assert all(len(item.artifact_ids) > 1 for item in evidence)


def test_low_value_outro_is_removed_from_summary() -> None:
    text = "视频介绍了七项更新，最后号召玩家点赞关注。核心是角色与玩法调整。"
    cleaned = _remove_low_value_meta(text)
    assert "号召" not in cleaned
    assert "核心是角色与玩法调整" in cleaned


def test_json_parser_accepts_markdown_fence() -> None:
    assert _parse_json_object('```json\n{"summary":"ok"}\n```') == {"summary": "ok"}
