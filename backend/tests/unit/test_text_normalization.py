from pathlib import Path
from uuid import uuid4

from lets_go_video_agent.domain.common import Provenance, TimeRange
from lets_go_video_agent.domain.timeline import TimelineArtifact, TimelineKind
from lets_go_video_agent.infrastructure.models.ollama_vision_client import (
    select_visual_frames,
)
from lets_go_video_agent.media.local_pipeline import (
    _extract_ocr_speaker_anchors,
    _select_speaker_clusters,
    build_fallback_chapters,
    build_semantic_windows,
    curate_representative_frames,
    normalize_chinese_text,
    validate_and_normalize_chapters,
)


def test_fallback_chapters_cover_video_without_model_output() -> None:
    video_id = uuid4()
    chapters = build_fallback_chapters(
        video_id=video_id,
        transcript=[{"start_ms": 1_000, "end_ms": 3_000, "text": "开场介绍游戏版本"}],
        duration_ms=200_000,
    )

    assert len(chapters) == 3
    assert chapters[0].time_range.start_ms == 0
    assert chapters[-1].time_range.end_ms == 200_000
    assert chapters[0].tags == ["fallback-chapter"]


def test_fallback_chapters_use_spoken_ordinals_and_fill_missing_boundary() -> None:
    transcript = [
        {"start_ms": 10_000, "end_ms": 11_000, "text": "第一 新角色与配队"},
        {"start_ms": 50_000, "end_ms": 51_000, "text": "第二 未来版本"},
        {"start_ms": 75_000, "end_ms": 76_000, "text": "第三 剧情地图"},
        {"start_ms": 130_000, "end_ms": 131_000, "text": "第五 核心玩法"},
        {"start_ms": 175_000, "end_ms": 176_000, "text": "第六 装饰拍照"},
        {"start_ms": 196_000, "end_ms": 197_000, "text": "第七 系统优化"},
    ]
    chapters = build_fallback_chapters(video_id=uuid4(), transcript=transcript, duration_ms=250_000)

    assert len(chapters) == 7
    assert chapters[3].time_range.start_ms == 102_500
    assert all(chapter.title.startswith("建议") for chapter in chapters)


def test_fallback_chapters_remain_monotonic_when_ordinals_are_mentioned_out_of_order() -> None:
    transcript = [
        {"start_ms": 100_000, "end_ms": 101_000, "text": "第一部分"},
        {"start_ms": 2_230_510, "end_ms": 2_231_000, "text": "第二个问题"},
        {"start_ms": 1_452_850, "end_ms": 1_453_000, "text": "第三点"},
    ]
    chapters = build_fallback_chapters(
        video_id=uuid4(), transcript=transcript, duration_ms=2_700_000
    )

    assert all(chapter.time_range.start_ms < chapter.time_range.end_ms for chapter in chapters)
    assert [chapter.time_range.start_ms for chapter in chapters] == sorted(
        chapter.time_range.start_ms for chapter in chapters
    )
    assert all(chapter.title.startswith("片段") for chapter in chapters)


def test_normalize_chinese_text_converts_traditional_and_whitespace() -> None:
    assert normalize_chinese_text("  視頻   異常檢測  ") == "视频 异常检测"


def test_semantic_windows_keep_speaker_and_cover_late_video_content() -> None:
    text = build_semantic_windows(
        transcript=[
            {"start_ms": 1_000, "end_ms": 2_000, "text": "开场", "speaker": "Speaker 1"},
            {
                "start_ms": 125_000,
                "end_ms": 126_000,
                "text": "最后的问题",
                "speaker": "Speaker 2",
            },
        ],
        ocr_items=[],
        duration_ms=130_000,
    )

    assert "Speaker 1:开场" in text
    assert "Speaker 2:最后的问题" in text
    assert "[120000-130000]" in text


def test_chapter_normalizer_rebuilds_continuous_ranges() -> None:
    chapters = validate_and_normalize_chapters(
        video_id=uuid4(),
        raw_chapters=[
            {"start_ms": 0, "end_ms": 80_000, "title": "问题一", "summary": "回答"},
            {"start_ms": 70_000, "end_ms": 120_000, "title": "问题二", "summary": "回答"},
            {"start_ms": 180_000, "end_ms": 220_000, "title": "问题三", "summary": "回答"},
        ],
        duration_ms=240_000,
        model_name="test",
        prompt_version="test",
    )

    assert [chapter.time_range.start_ms for chapter in chapters] == [0, 70_000, 180_000]
    assert [chapter.time_range.end_ms for chapter in chapters] == [70_000, 180_000, 240_000]


def test_speaker_cluster_selector_detects_two_clear_groups() -> None:
    import numpy as np

    first = np.tile(np.array([-4.0, -4.0]), (20, 1))
    second = np.tile(np.array([4.0, 4.0]), (20, 1))
    labels = _select_speaker_clusters(np.vstack([first, second]), max_speakers=4)

    assert len(set(labels.tolist())) == 2


def test_speaker_cluster_selector_keeps_one_voice_with_gradual_timbre_change() -> None:
    import numpy as np

    # 模拟同一个人在视频前后音量、语气缓慢变化；不应因此制造第二位说话人。
    progression = np.linspace(-0.8, 0.8, 80)
    matrix = np.column_stack([progression, progression * 0.35, progression * -0.2])
    labels = _select_speaker_clusters(matrix, max_speakers=4)

    assert len(set(labels.tolist())) == 1


def test_visual_frame_selection_is_bounded_and_covers_both_ends() -> None:
    frames = [{"timestamp_ms": index * 1_000, "path": Path(f"{index}.jpg")} for index in range(100)]

    selected = select_visual_frames(frames, max_frames=24)

    assert len(selected) == 24
    assert selected[0]["timestamp_ms"] == 0
    assert selected[-1]["timestamp_ms"] == 99_000


def test_ocr_speaker_anchor_uses_quote_instead_of_nearest_timestamp() -> None:
    transcript = [
        {"start_ms": 9_000, "end_ms": 10_000, "text": "那我们进入下一个问题"},
        {"start_ms": 11_000, "end_ms": 13_000, "text": "我最喜欢的是塔防策略部分"},
        {"start_ms": 14_000, "end_ms": 15_000, "text": "确实很有意思"},
    ]
    anchors = _extract_ocr_speaker_anchors(
        ["糯米", "流星飞"],
        transcript,
        [
            {
                "timestamp_ms": 10_000,
                "text": "主持人：糯米 嘉宾：@流星飞 / 流星飞：我最喜欢塔防策略部分",
            }
        ],
    )

    assert anchors == {"糯米": [], "流星飞": [1]}


def test_ocr_speaker_anchor_ignores_participant_roster() -> None:
    anchors = _extract_ocr_speaker_anchors(
        ["糯米", "克斯"],
        [{"start_ms": 1_000, "end_ms": 2_000, "text": "欢迎大家"}],
        [{"timestamp_ms": 1_000, "text": "主持人：糯米 嘉宾：@克斯"}],
    )

    assert anchors == {"糯米": [], "克斯": []}


def test_ocr_question_label_becomes_host_anchor() -> None:
    anchors = _extract_ocr_speaker_anchors(
        ["糯米", "克斯"],
        [
            {"start_ms": 8_000, "end_ms": 10_000, "text": "你最喜欢哪一段剧情"},
            {"start_ms": 11_000, "end_ms": 13_000, "text": "我喜欢开服剧情"},
        ],
        [
            {
                "timestamp_ms": 10_000,
                "text": "Q：你最喜欢哪一段剧情？ / 克斯：我喜欢开服剧情",
            }
        ],
    )

    assert anchors == {"糯米": [0], "克斯": [1]}


def test_representative_frames_are_numbered_and_selected_by_chapter() -> None:
    video_id = uuid4()
    frames = [
        {"timestamp_ms": timestamp, "path": Path(f"{timestamp:010d}.jpg")}
        for timestamp in range(0, 240_000, 30_000)
    ]
    chapters = [
        TimelineArtifact(
            video_id=video_id,
            kind=TimelineKind.CHAPTER,
            time_range=TimeRange(start_ms=0, end_ms=120_000),
            title="第一节",
            text="第一节摘要",
            provenance=Provenance(producer="test"),
        ),
        TimelineArtifact(
            video_id=video_id,
            kind=TimelineKind.CHAPTER,
            time_range=TimeRange(start_ms=120_000, end_ms=240_000),
            title="第二节",
            text="第二节摘要",
            provenance=Provenance(producer="test"),
        ),
    ]

    result = curate_representative_frames(
        video_id=video_id,
        frames=frames,
        ocr_items=[],
        chapters=chapters,
        duration_ms=240_000,
    )

    assert [item.title for item in result] == [
        "01-01｜第一节",
        "01-02｜第一节",
        "02-01｜第二节",
        "02-02｜第二节",
    ]
    assert [item.time_range.start_ms for item in result] == [30_000, 90_000, 150_000, 210_000]
