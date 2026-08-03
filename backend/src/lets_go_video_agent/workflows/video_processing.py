from __future__ import annotations

from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.common import RetryPolicy

from lets_go_video_agent.workflows.contracts import ProcessingRequest, ProcessingResult


@workflow.defn(name="video-processing")
class VideoProcessingWorkflow:
    """P0 可恢复的媒体处理骨架。

    当前只贯通 probe 和音轨提取两个真实步骤。ASR/OCR/VLM 尚未实现，
    因此返回的 limitations 会明确说明边界，不会生成伪时间轴。
    """

    def __init__(self) -> None:
        self._stage = "queued"
        self._cancel_requested = False

    @workflow.query
    def current_stage(self) -> str:
        return self._stage

    @workflow.signal
    async def request_cancel(self) -> None:
        self._cancel_requested = True

    @workflow.run
    async def run(self, request: ProcessingRequest) -> ProcessingResult:
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=20),
            maximum_attempts=3,
        )

        self._stage = "probing"
        probe = cast(
            dict[str, object],
            await workflow.execute_activity(
                "probe_media",
                request,
                result_type=dict,
                start_to_close_timeout=timedelta(minutes=2),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=retry_policy,
            ),
        )
        if self._cancel_requested:
            self._stage = "cancelled"
            return ProcessingResult(
                video_id=request.video_id,
                status="cancelled",
                stage=self._stage,
                probe=probe,
            )

        self._stage = "extracting_audio"
        audio_object_key = cast(
            str,
            await workflow.execute_activity(
                "extract_audio",
                request,
                result_type=str,
                start_to_close_timeout=timedelta(minutes=15),
                heartbeat_timeout=timedelta(seconds=60),
                retry_policy=retry_policy,
            ),
        )
        self._stage = "media_ready"
        return ProcessingResult(
            video_id=request.video_id,
            status="partially_ready",
            stage=self._stage,
            probe=probe,
            audio_object_key=audio_object_key,
            limitations=("ASR、说话人分离、OCR、镜头检测和 VLM 尚未接入当前 Workflow。",),
        )
