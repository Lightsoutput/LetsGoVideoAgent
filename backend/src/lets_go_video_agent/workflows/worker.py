from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from lets_go_video_agent.config import get_settings
from lets_go_video_agent.workflows.activities import VideoProcessingActivities
from lets_go_video_agent.workflows.video_processing import VideoProcessingWorkflow


async def serve() -> None:
    settings = get_settings()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    activities = VideoProcessingActivities(settings)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[VideoProcessingWorkflow],
        activities=[activities.probe_media, activities.extract_audio],
    )
    logging.getLogger(__name__).info(
        "Temporal Worker started on task queue %s",
        settings.temporal_task_queue,
    )
    await worker.run()


def run() -> None:
    """Console script 入口；进程由 tini/Temporal Worker 处理退出信号。"""

    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())


if __name__ == "__main__":
    run()
