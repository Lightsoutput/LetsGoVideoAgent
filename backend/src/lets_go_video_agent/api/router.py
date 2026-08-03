from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from lets_go_video_agent import __version__
from lets_go_video_agent.agents.harness.models import AgentRun
from lets_go_video_agent.api.dependencies import get_container
from lets_go_video_agent.api.schemas import (
    AskQuestionRequest,
    HealthResponse,
    TimelineResponse,
    VideoListResponse,
    WebImportRequest,
)
from lets_go_video_agent.bootstrap import Container
from lets_go_video_agent.domain.processing import ProcessingRun
from lets_go_video_agent.domain.qa import Answer
from lets_go_video_agent.domain.video import Video

router = APIRouter()


async def _local_video_path(video_id: UUID, container: Container) -> Path:
    """解析上传视频路径，并在统一边界完成越界与存在性检查。"""

    video = await container.videos.get_video(video_id)
    if not video.source_object_key:
        raise HTTPException(status_code=404, detail="该视频没有可播放的本地媒体")
    root = container.settings.local_data_dir.resolve()
    target = (root / video.source_object_key).resolve()
    if root not in target.parents or not target.exists():
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    return target


@router.get("/health/live", response_model=HealthResponse, tags=["health"])
async def live(container: Annotated[Container, Depends(get_container)]) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        repository=container.settings.repository_backend,
    )


@router.get("/health/ready", response_model=HealthResponse, tags=["health"])
async def ready(container: Annotated[Container, Depends(get_container)]) -> HealthResponse:
    await container.store.ping()
    return HealthResponse(
        status="ready",
        version=__version__,
        repository=container.settings.repository_backend,
    )


@router.get("/videos", response_model=VideoListResponse, tags=["videos"])
async def list_videos(
    container: Annotated[Container, Depends(get_container)],
) -> VideoListResponse:
    return VideoListResponse(items=await container.videos.list_videos())


@router.get("/videos/{video_id}", response_model=Video, tags=["videos"])
async def get_video(
    video_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> Video:
    return await container.videos.get_video(video_id)


@router.post(
    "/videos/imports",
    response_model=Video,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["videos"],
)
async def import_video(
    payload: WebImportRequest,
    container: Annotated[Container, Depends(get_container)],
) -> Video:
    video = await container.videos.import_web(
        url=payload.url,
        title=payload.title,
        rights_confirmed=payload.rights_confirmed,
    )
    if payload.rights_confirmed:
        container.processing.start(video.id)
    return video


@router.post(
    "/videos/uploads",
    response_model=Video,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["videos"],
)
async def upload_video(
    container: Annotated[Container, Depends(get_container)],
    file: Annotated[UploadFile, File(description="MP4/MOV/MKV/WebM 视频文件")],
) -> Video:
    video = await container.videos.upload(file)
    container.processing.start(video.id)
    return video


@router.post("/videos/{video_id}/processing", response_model=ProcessingRun, tags=["processing"])
async def start_processing(
    video_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> ProcessingRun:
    await container.videos.get_video(video_id)
    return container.processing.start(video_id)


@router.get("/videos/{video_id}/processing", response_model=ProcessingRun, tags=["processing"])
async def get_processing(
    video_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> ProcessingRun:
    run = container.processing.get(video_id)
    if run is None:
        raise HTTPException(status_code=404, detail="该视频还没有处理任务")
    return run


@router.get("/costs/summary", tags=["cost"])
async def get_cost_summary(
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, object]:
    return container.cost_ledger.summary()


@router.get("/videos/{video_id}/frames/{filename}", include_in_schema=False)
async def get_real_frame(
    video_id: UUID,
    filename: str,
    container: Annotated[Container, Depends(get_container)],
) -> FileResponse:
    if Path(filename).name != filename or not filename.endswith(".jpg"):
        raise HTTPException(status_code=400, detail="非法帧文件名")
    root = (container.settings.local_data_dir / "frames" / str(video_id)).resolve()
    target = (root / filename).resolve()
    if root not in target.parents or not target.exists():
        raise HTTPException(status_code=404, detail="帧不存在")
    return FileResponse(target, media_type="image/jpeg")


@router.get("/videos/{video_id}/media", include_in_schema=False)
async def stream_video(
    video_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> FileResponse:
    """浏览器原生视频源；Starlette FileResponse 支持 Range/206 请求。"""

    target = await _local_video_path(video_id, container)
    media_types = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }
    return FileResponse(
        target,
        media_type=media_types.get(target.suffix.lower(), "application/octet-stream"),
        filename=target.name,
        content_disposition_type="inline",
    )


@router.get("/videos/{video_id}/frame-at/{timestamp_ms}.jpg", include_in_schema=False)
async def frame_at(
    video_id: UUID,
    timestamp_ms: int,
    container: Annotated[Container, Depends(get_container)],
) -> FileResponse:
    """按时间戳返回真实视频帧，供当前帧问答和证据卡片使用。"""

    if timestamp_ms < 0:
        raise HTTPException(status_code=400, detail="时间戳不能小于 0")
    source = await _local_video_path(video_id, container)
    cache_dir = container.settings.local_data_dir.resolve() / "frames-on-demand" / str(video_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{timestamp_ms:010d}.jpg"
    if not target.exists():
        from lets_go_video_agent.media.local_pipeline import extract_frame_at

        try:
            await extract_frame_at(source, target, timestamp_ms)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="无法提取目标视频帧") from exc
    return FileResponse(target, media_type="image/jpeg")


@router.get(
    "/videos/{video_id}/timeline",
    response_model=TimelineResponse,
    tags=["timeline"],
)
async def get_timeline(
    video_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> TimelineResponse:
    items = await container.videos.get_timeline(video_id)
    return TimelineResponse(video_id=video_id, items=items)


@router.post(
    "/videos/{video_id}/questions",
    response_model=Answer,
    tags=["agent"],
)
async def ask_video(
    video_id: UUID,
    payload: AskQuestionRequest,
    container: Annotated[Container, Depends(get_container)],
) -> Answer:
    return await container.questions.ask(
        video_id=video_id,
        query=payload.query,
        target=payload.target,
        conversation_id=payload.conversation_id,
    )


@router.get("/agent-runs/{run_id}", response_model=AgentRun, tags=["agent"])
async def get_agent_run(
    run_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> AgentRun:
    run = await container.store.get_run(run_id)
    if run is None:
        # 交给统一错误中间件的下一版；当前返回标准 404 Response。
        from lets_go_video_agent.application.errors import NotFoundError

        raise NotFoundError(f"未找到 Agent Run: {run_id}")
    return AgentRun.model_validate(run)


@router.get("/demo/frames/{timestamp_ms}.svg", include_in_schema=False)
async def demo_frame(
    timestamp_ms: int,
    label: Annotated[str, Query(max_length=80)] = "synthetic-frame",
) -> Response:
    """生成不含版权素材的 SVG 帧，供证据卡片和 E2E 测试使用。"""

    safe_label = escape(label)
    seconds = timestamp_ms / 1_000
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540">
<defs><linearGradient id="g" x1="0" x2="1"><stop stop-color="#07111f"/>
<stop offset="1" stop-color="#143b50"/></linearGradient></defs>
<rect width="960" height="540" fill="url(#g)"/>
<rect x="56" y="62" width="848" height="416" rx="22" fill="#0b1726" stroke="#28d7a1"/>
<text x="88" y="124" fill="#8ea4b8" font-family="sans-serif" font-size="22">
LetsGoVideoAgent · synthetic evidence</text>
<text x="88" y="222" fill="#f4f7fb" font-family="sans-serif" font-size="52">
{safe_label}</text>
<text x="88" y="298" fill="#28d7a1" font-family="monospace" font-size="38">
timestamp {seconds:.3f}s</text>
<text x="88" y="418" fill="#8ea4b8" font-family="sans-serif" font-size="18">
This image is generated locally and is not a frame from a third-party video.</text>
</svg>"""
    return Response(content=svg, media_type="image/svg+xml")
