"""用现有字幕缓存验收全片总结，不重复下载或执行 Whisper/OCR。"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx

from lets_go_video_agent.bootstrap import build_container
from lets_go_video_agent.config import Settings
from lets_go_video_agent.domain.common import Provenance, TimeRange
from lets_go_video_agent.domain.timeline import TimelineArtifact, TimelineKind
from lets_go_video_agent.domain.video import UploadSource, Video, VideoStatus


async def main() -> None:
    settings = Settings(seed_demo_data=False)
    transcript_path = (
        settings.local_data_dir / "processing-cache" / "BV1tMG86YEmW.small.transcript.json"
    )
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    video_id = uuid4()
    container = build_container(settings)
    video = Video(
        id=video_id,
        title="【新版本必看】蓄意轰拳，豪情满天！弭弗卡缪实装！",
        source=UploadSource(
            original_filename="BV1tMG86YEmW.mp4",
            content_type="video/mp4",
            size_bytes=88_968_866,
        ),
        status=VideoStatus.READY,
        duration_ms=253_461,
    )
    await container.store.add(video)
    await container.store.add_many(
        [
            TimelineArtifact(
                video_id=video_id,
                kind=TimelineKind.TRANSCRIPT,
                time_range=TimeRange(
                    start_ms=int(item["start_ms"]),
                    end_ms=int(item["end_ms"]),
                ),
                text=str(item["text"]),
                confidence=0.9,
                provenance=Provenance(producer="faster-whisper", model="small"),
            )
            for item in transcript
        ]
    )
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "http://127.0.0.1:8000/api/v1/videos/"
            "644d132c-2d61-4e5d-8565-5ab45f01f32e/timeline"
        )
        response.raise_for_status()
    visual_artifacts = [
        TimelineArtifact.model_validate(item).model_copy(update={"video_id": video_id})
        for item in response.json()["items"]
        if item["kind"] in {"ocr", "visual"}
    ]
    await container.store.add_many(visual_artifacts)
    answer = await container.questions.ask(
        video_id=video_id,
        query="请全面总结这个视频的主要内容，并解释每项建议的具体含义",
    )
    print(
        json.dumps(
            {
                "status": answer.status,
                "text": answer.text,
                "citation_timestamps_ms": [item.timestamp_ms for item in answer.citations],
                "limitations": answer.limitations,
                "usage": answer.usage.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
