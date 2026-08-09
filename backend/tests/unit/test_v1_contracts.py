import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from lets_go_video_agent.domain.common import Provenance, TimeRange
from lets_go_video_agent.domain.observability import TraceEvent, TraceEventType, UsageEvent
from lets_go_video_agent.domain.processing import ProcessingRun
from lets_go_video_agent.domain.semantic import NarrativeContext, SemanticEvent
from lets_go_video_agent.domain.timeline import ObservationType, TimelineArtifact, TimelineKind
from lets_go_video_agent.infrastructure.memory import InMemoryStore
from lets_go_video_agent.media.local_pipeline import (
    LocalProcessingManager,
    build_semantic_understanding,
)


def test_semantic_contract_keeps_high_level_meaning_linked_to_evidence() -> None:
    video_id = uuid4()
    evidence_id = uuid4()
    event = SemanticEvent(
        video_id=video_id,
        time_range=TimeRange(start_ms=1_000, end_ms=8_000),
        event_type="explanation",
        title="解释核心机制",
        summary="讲解者展示界面并解释该机制会怎样影响后续操作。",
        participants=["讲解者"],
        actions=["展示界面", "解释影响"],
        evidence_ids=[evidence_id],
        provenance=Provenance(producer="test-understanding-agent"),
    )

    assert event.evidence_ids == [evidence_id]
    assert event.time_range.duration_ms == 7_000


def test_semantic_understanding_links_chapters_to_multimodal_observations() -> None:
    video_id = uuid4()
    provenance = Provenance(producer="test")
    chapter = TimelineArtifact(
        video_id=video_id,
        kind=TimelineKind.CHAPTER,
        time_range=TimeRange(start_ms=0, end_ms=30_000),
        title="01-01｜介绍操作目标",
        text="讲解者先说明本节目标，再展示操作入口。",
        confidence=0.82,
        observation_type=ObservationType.INFERENCE,
        provenance=provenance,
    )
    transcript = TimelineArtifact(
        video_id=video_id,
        kind=TimelineKind.TRANSCRIPT,
        time_range=TimeRange(start_ms=1_000, end_ms=5_000),
        text="我们先看一下本次操作的目标。",
        speaker="讲解者",
        provenance=provenance,
    )

    events, narrative = build_semantic_understanding(
        video_id=video_id,
        artifacts=[chapter, transcript],
        visual_items=[
            {
                "timestamp_ms": 3_000,
                "scene": "软件操作界面",
                "actions": ["打开入口"],
                "entities": ["设置面板"],
            }
        ],
        video_format="教程",
        purpose="帮助观众完成设置",
        overall_summary="视频说明设置目标并演示入口。",
        model_name="test-model",
    )

    assert len(events) == 1
    assert events[0].title == "介绍操作目标"
    assert events[0].participants == ["讲解者"]
    assert events[0].entities == ["设置面板"]
    assert chapter.id in events[0].artifact_ids
    assert narrative is not None
    assert narrative.event_ids == [events[0].id]
    assert narrative.video_format == "教程"


@pytest.mark.asyncio
async def test_memory_store_persists_v1_processing_semantic_and_observability_data() -> None:
    store = InMemoryStore()
    video_id = uuid4()
    run = ProcessingRun(video_id=video_id)
    semantic_event = SemanticEvent(
        video_id=video_id,
        time_range=TimeRange(start_ms=0, end_ms=10_000),
        event_type="introduction",
        title="说明视频目标",
        summary="创作者介绍视频将解决的问题。",
        provenance=Provenance(producer="test"),
    )
    narrative = NarrativeContext(
        video_id=video_id,
        video_format="tutorial",
        purpose="帮助观众完成一项操作",
        summary="视频先说明目标，再演示操作并解释结果。",
        event_ids=[semantic_event.id],
        provenance=Provenance(producer="test"),
    )
    trace = TraceEvent(
        trace_id=run.trace_id,
        sequence=1,
        event_type=TraceEventType.AGENT_STARTED,
        name="understanding-agent",
        video_id=video_id,
        task_id=run.id,
    )
    usage = UsageEvent(
        provider="test-provider",
        model="test-model",
        purpose="video_understanding",
        cost_cny=Decimal("0.0123"),
        original_cost=Decimal("0.0123"),
        trace_id=run.trace_id,
        task_id=run.id,
        video_id=video_id,
    )

    await store.upsert_processing_run(run)
    await store.replace_semantic_events(video_id, [semantic_event])
    await store.upsert_narrative_context(narrative)
    await store.append_trace_event(trace)
    await store.append_usage_event(usage)

    assert await store.get_processing_run(video_id) == run
    assert list(await store.list_semantic_events(video_id)) == [semantic_event]
    assert await store.get_narrative_context(video_id) == narrative
    assert list(await store.list_trace_events(run.trace_id)) == [trace]
    assert list(await store.list_usage_events(video_id)) == [usage]


@pytest.mark.asyncio
async def test_processing_stages_emit_deduplicated_live_trace_events(tmp_path) -> None:
    store = InMemoryStore()
    manager = LocalProcessingManager(
        store=store,
        data_dir=tmp_path,
        asr_model="tiny",
        llm=None,
    )
    run = ProcessingRun(video_id=uuid4())

    await manager._emit_processing_stage(
        run,
        stage="queued",
        label="启动工作流",
        progress=0,
        message="装配 Agent",
    )
    await manager._emit_processing_stage(
        run,
        stage="probing",
        label="读取媒体信息",
        progress=0.05,
        message="读取编码",
    )
    await manager._emit_processing_stage(
        run,
        stage="probing",
        label="读取媒体信息",
        progress=0.08,
        message="重复进度刷新",
    )

    events = list(await store.list_trace_events(run.trace_id))
    assert [event.event_type for event in events] == [
        TraceEventType.WORKFLOW_STARTED,
        TraceEventType.AGENT_STARTED,
    ]
    assert events[1].name == "ingestion_agent"
    assert events[1].attributes["stage"] == "probing"


@pytest.mark.asyncio
async def test_processing_agents_can_run_in_parallel_and_keep_trace_order(tmp_path) -> None:
    store = InMemoryStore()
    manager = LocalProcessingManager(
        store=store,
        data_dir=tmp_path,
        asr_model="tiny",
        llm=None,
    )
    run = ProcessingRun(video_id=uuid4())
    release = asyncio.Event()
    started = 0

    async def branch(name: str) -> str:
        nonlocal started
        started += 1
        if started == 2:
            release.set()
        await release.wait()
        return name

    results = await asyncio.gather(
        manager._run_processing_agent(
            run,
            name="audio_perception_agent",
            label="音频感知",
            phase="并行感知",
            operation=lambda: branch("audio"),
            depends_on=["ingestion_agent"],
            parallel_group="perception",
        ),
        manager._run_processing_agent(
            run,
            name="visual_sampling_agent",
            label="视觉采样",
            phase="并行感知",
            operation=lambda: branch("visual"),
            depends_on=["ingestion_agent"],
            parallel_group="perception",
        ),
    )

    events = list(await store.list_trace_events(run.trace_id))
    assert set(results) == {"audio", "visual"}
    assert [event.event_type for event in events[:2]] == [
        TraceEventType.AGENT_STARTED,
        TraceEventType.AGENT_STARTED,
    ]
    assert {event.name for event in events[:2]} == {
        "audio_perception_agent",
        "visual_sampling_agent",
    }
    assert all(event.attributes["parallel_group"] == "perception" for event in events)
