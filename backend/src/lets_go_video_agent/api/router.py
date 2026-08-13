from __future__ import annotations

import asyncio
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from lets_go_video_agent import __version__
from lets_go_video_agent.agents.harness.models import AgentRun
from lets_go_video_agent.api.dependencies import get_container
from lets_go_video_agent.api.schemas import (
    AddSkillProjectUrlsRequest,
    AskQuestionRequest,
    AttachProjectSkillRequest,
    BindSkillRequest,
    CreateSkillProjectRequest,
    DeleteSkillsRequest,
    GenerateSkillRequest,
    HarnessPolicyResponse,
    HealthResponse,
    McpStatusResponse,
    ModelRouteResponse,
    NarrativeContextResponse,
    RefineSkillRequest,
    RegenerateSkillRequest,
    RollbackSkillRequest,
    RuntimeComponentResponse,
    SemanticEventsResponse,
    SkillListResponse,
    SkillProjectListResponse,
    SystemObservabilityResponse,
    TimelineResponse,
    TraceEventsResponse,
    UsageEventsResponse,
    VideoListResponse,
    WebImportRequest,
)
from lets_go_video_agent.bootstrap import Container
from lets_go_video_agent.domain.processing import ProcessingRun
from lets_go_video_agent.domain.qa import Answer
from lets_go_video_agent.domain.skill import SkillDetail, SkillProjectWorkspace
from lets_go_video_agent.domain.video import Video
from lets_go_video_agent.media.video_library import resolve_video_source

router = APIRouter()


async def _searxng_health(api_base: str) -> bool:
    """直接检查搜索引擎层，让 UI 能区分 SearXNG 故障与 MCP 协议故障。"""

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(
                f"{api_base.rstrip('/')}/search",
                params={"q": "LetsGoVideoAgent", "format": "json"},
            )
        return response.status_code == 200
    except httpx.HTTPError:
        return False


async def _local_video_path(video_id: UUID, container: Container) -> Path:
    """解析上传视频路径，并在统一边界完成越界与存在性检查。"""

    video = await container.videos.get_video(video_id)
    if not video.source_object_key:
        raise HTTPException(status_code=404, detail="该视频没有可播放的本地媒体")
    try:
        target = resolve_video_source(
            object_key=video.source_object_key,
            data_dir=container.settings.local_data_dir,
            library_dir=container.settings.video_library_dir,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="媒体文件路径无效") from exc
    if not target.exists():
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


@router.get("/skills", response_model=SkillListResponse, tags=["skills"])
async def list_skills(
    container: Annotated[Container, Depends(get_container)],
) -> SkillListResponse:
    return SkillListResponse(items=await container.skills.list_skills())


@router.get("/skill-projects", response_model=SkillProjectListResponse, tags=["skills"])
async def list_skill_projects(
    container: Annotated[Container, Depends(get_container)],
) -> SkillProjectListResponse:
    return SkillProjectListResponse(items=await container.skill_projects.list_projects())


@router.post(
    "/skill-projects",
    response_model=SkillProjectWorkspace,
    status_code=status.HTTP_201_CREATED,
    tags=["skills"],
)
async def create_skill_project(
    payload: CreateSkillProjectRequest,
    container: Annotated[Container, Depends(get_container)],
) -> SkillProjectWorkspace:
    return await container.skill_projects.create(
        name=payload.name,
        goal=payload.goal,
        description=payload.description,
    )


@router.get(
    "/skill-projects/{project_id}",
    response_model=SkillProjectWorkspace,
    tags=["skills"],
)
async def get_skill_project(
    project_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> SkillProjectWorkspace:
    return await container.skill_projects.get(project_id)


@router.delete(
    "/skill-projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["skills"],
)
async def delete_skill_project(
    project_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    await container.skill_projects.delete(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/skill-projects/{project_id}/videos",
    response_model=SkillProjectWorkspace,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["skills"],
)
async def add_skill_project_videos(
    project_id: UUID,
    payload: AddSkillProjectUrlsRequest,
    container: Annotated[Container, Depends(get_container)],
) -> SkillProjectWorkspace:
    return await container.skill_projects.add_urls(
        project_id=project_id,
        urls=payload.urls,
        rights_confirmed=payload.rights_confirmed,
    )


@router.post(
    "/skill-projects/{project_id}/items/{item_id}/retry",
    response_model=SkillProjectWorkspace,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["skills"],
)
async def retry_skill_project_item(
    project_id: UUID,
    item_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> SkillProjectWorkspace:
    return await container.skill_projects.retry(project_id, item_id)


@router.post(
    "/skill-projects/{project_id}/skill",
    response_model=SkillProjectWorkspace,
    tags=["skills"],
)
async def attach_project_skill(
    project_id: UUID,
    payload: AttachProjectSkillRequest,
    container: Annotated[Container, Depends(get_container)],
) -> SkillProjectWorkspace:
    return await container.skill_projects.attach_skill(project_id, payload.skill_id)


@router.post(
    "/skills/generate",
    response_model=SkillDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["skills"],
)
async def generate_skill(
    payload: GenerateSkillRequest,
    container: Annotated[Container, Depends(get_container)],
) -> SkillDetail:
    return await container.skills.generate(
        video_ids=payload.video_ids,
        user_goal=payload.goal,
        display_name=payload.display_name,
    )


@router.post(
    "/skills/batch-delete",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["skills"],
)
async def batch_delete_skills(
    payload: DeleteSkillsRequest,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    await container.skills.delete_many(payload.skill_ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/skills/{skill_id}/regenerate",
    response_model=SkillDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["skills"],
)
async def regenerate_skill(
    skill_id: UUID,
    payload: RegenerateSkillRequest,
    container: Annotated[Container, Depends(get_container)],
) -> SkillDetail:
    """保留既有 Skill 与版本，使用最新样本创建一个新的待审核版本。"""

    return await container.skills.regenerate(
        skill_id=skill_id,
        video_ids=payload.video_ids,
        user_goal=payload.goal,
    )


@router.get("/skills/{skill_id}", response_model=SkillDetail, tags=["skills"])
async def get_skill(
    skill_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> SkillDetail:
    return await container.skills.get(skill_id)


@router.delete(
    "/skills/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["skills"],
)
async def delete_skill(
    skill_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    await container.skills.delete_many([skill_id])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/skills/{skill_id}/refine",
    response_model=SkillDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["skills"],
)
async def refine_skill(
    skill_id: UUID,
    payload: RefineSkillRequest,
    container: Annotated[Container, Depends(get_container)],
) -> SkillDetail:
    return await container.skills.refine(
        skill_id=skill_id,
        instruction=payload.instruction,
        base_version=payload.base_version,
    )


@router.post(
    "/skills/{skill_id}/versions/{version}/publish",
    response_model=SkillDetail,
    tags=["skills"],
)
async def publish_skill(
    skill_id: UUID,
    version: int,
    container: Annotated[Container, Depends(get_container)],
) -> SkillDetail:
    return await container.skills.publish(skill_id, version)


@router.post("/skills/{skill_id}/rollback", response_model=SkillDetail, tags=["skills"])
async def rollback_skill(
    skill_id: UUID,
    payload: RollbackSkillRequest,
    container: Annotated[Container, Depends(get_container)],
) -> SkillDetail:
    return await container.skills.rollback(skill_id, payload.version)


@router.post("/skills/{skill_id}/bindings", response_model=SkillDetail, tags=["skills"])
async def bind_skill(
    skill_id: UUID,
    payload: BindSkillRequest,
    container: Annotated[Container, Depends(get_container)],
) -> SkillDetail:
    return await container.skills.bind(skill_id, payload.video_ids)


@router.get("/videos/{video_id}/skill", response_model=SkillDetail, tags=["skills"])
async def get_video_skill(
    video_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> SkillDetail:
    active = await container.skills.active_for_video(video_id)
    if active is None:
        raise HTTPException(status_code=404, detail="该视频未绑定已发布 Skill")
    return await container.skills.get(active[0].id)


@router.delete(
    "/videos/{video_id}/skill",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["skills"],
)
async def unbind_video_skill(
    video_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    await container.skills.unbind(video_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    if payload.rights_confirmed and video.status != "ready":
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
        run = await container.store.get_processing_run(video_id)
    if run is None:
        raise HTTPException(status_code=404, detail="该视频还没有处理任务")
    return run


@router.get("/costs/summary", tags=["cost"])
async def get_cost_summary(
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, object]:
    return container.cost_ledger.summary()


@router.get("/observability/usage", response_model=UsageEventsResponse, tags=["observability"])
async def get_usage_events(
    container: Annotated[Container, Depends(get_container)],
    video_id: UUID | None = None,
    trace_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 200,
) -> UsageEventsResponse:
    """返回统一用量事件，供成本中心按服务商和模型聚合展示。"""

    all_items = list(await container.store.list_usage_events(video_id, trace_id))
    items = all_items[-limit:]
    by_provider: dict[str, Decimal] = {}
    by_model: dict[str, Decimal] = {}
    for item in all_items:
        by_provider[item.provider] = by_provider.get(item.provider, Decimal()) + item.cost_cny
        by_model[item.model] = by_model.get(item.model, Decimal()) + item.cost_cny
    return UsageEventsResponse(
        items=items,
        call_count=len(all_items),
        total_input_tokens=sum(item.input_tokens for item in all_items),
        total_output_tokens=sum(item.output_tokens for item in all_items),
        total_cost_cny=sum((item.cost_cny for item in all_items), Decimal()),
        cost_by_provider=by_provider,
        cost_by_model=by_model,
    )


@router.get(
    "/observability/system",
    response_model=SystemObservabilityResponse,
    tags=["observability"],
)
async def get_observability_system(
    container: Annotated[Container, Depends(get_container)],
) -> SystemObservabilityResponse:
    """公开安全的运行配置，不返回 API Key、Prompt 或代理凭据。"""

    settings = container.settings
    budget = container.questions.default_budget
    search_client = container.search
    if search_client is None:
        mcp_status = "disabled"
        searxng_status = "disabled"
    else:

        async def check_mcp_with_retry() -> bool:
            # MCP Streamable HTTP 会话在监督器并发探测或刚完成自愈时可能瞬时失败；
            # 短间隔重试一次，避免把健康服务错误显示为“不可用”。
            for attempt in range(2):
                try:
                    if await asyncio.wait_for(search_client.health(), timeout=5):
                        return True
                except TimeoutError:
                    pass
                if attempt == 0:
                    await asyncio.sleep(0.3)
            return False

        mcp_result, searxng_result = await asyncio.gather(
            check_mcp_with_retry(),
            asyncio.wait_for(_searxng_health(settings.search_api_base), timeout=4),
            return_exceptions=True,
        )
        mcp_status = "ready" if mcp_result is True else "unavailable"
        # search_health 工具本身会访问下游 SearXNG；MCP 检查成功时可直接证明
        # 搜索引擎可用，避免独立 HTTP 探针偶发超时造成相互矛盾的状态。
        searxng_status = "ready" if searxng_result is True or mcp_result is True else "unavailable"

    model_routes = [
        ModelRouteResponse(
            capability="text_reasoning",
            provider=settings.llm_provider,
            model=settings.llm_model,
            configured=settings.llm_provider == "mock" or bool(settings.llm_api_key),
        ),
        ModelRouteResponse(
            capability="visual_understanding",
            provider=settings.vlm_provider,
            model=settings.vlm_model,
            configured=settings.vlm_provider in {"mock", "ollama"} or bool(settings.vlm_api_key),
        ),
    ]
    skill_count = len(await container.skills.list_skills())
    return SystemObservabilityResponse(
        harness=HarnessPolicyResponse(
            max_steps=budget.max_steps,
            max_model_calls=budget.max_model_calls,
            max_tool_calls=budget.max_tool_calls,
            max_tokens=budget.max_tokens,
            max_cost_usd=budget.max_cost_usd,
            deadline_seconds=budget.deadline_seconds,
            max_repeated_tool_call=budget.max_repeated_tool_call,
            registered_tools=sorted(container.harness.registry.names),
        ),
        mcp=McpStatusResponse(
            provider=settings.search_provider,
            status=mcp_status,
            endpoint=(settings.search_mcp_url if settings.search_provider == "mcp" else None),
            tools=(
                ["search_web", "verify_terms", "search_health"]
                if settings.search_provider == "mcp"
                else []
            ),
        ),
        models=model_routes,
        repository=settings.repository_backend,
        workflow=settings.workflow_backend,
        runtime_components=[
            RuntimeComponentResponse(
                id="harness",
                name="Agent Harness",
                kind="harness",
                status="ready",
                summary="预算、工具白名单、参数校验与截止时间策略已装载",
            ),
            RuntimeComponentResponse(
                id="memory",
                name="视频记忆",
                kind="memory",
                status="ready",
                summary=f"{settings.repository_backend} Repository 已连接",
                depends_on=["harness"],
            ),
            RuntimeComponentResponse(
                id="searxng",
                name="SearXNG",
                kind="search",
                status=searxng_status,
                summary=(
                    "搜索引擎可用"
                    if searxng_status == "ready"
                    else "搜索引擎未响应，请运行 scripts/start-searxng.ps1"
                ),
                endpoint=(settings.search_api_base if container.search is not None else None),
            ),
            RuntimeComponentResponse(
                id="search_mcp",
                name="Search MCP",
                kind="mcp",
                status=mcp_status,
                summary=(
                    "MCP 协议与搜索工具可调用"
                    if mcp_status == "ready"
                    else "MCP 未连接；先确认 SearXNG，再检查 8090 端口"
                ),
                endpoint=(settings.search_mcp_url if container.search is not None else None),
                depends_on=["searxng"],
            ),
            *[
                RuntimeComponentResponse(
                    id=f"model_{route.capability}",
                    name="文本推理模型" if route.capability == "text_reasoning" else "视觉理解模型",
                    kind="model",
                    status="ready" if route.configured else "unavailable",
                    summary=f"{route.provider} / {route.model}",
                    depends_on=["harness"],
                )
                for route in model_routes
            ],
            RuntimeComponentResponse(
                id="trace_store",
                name="Trace Store",
                kind="trace",
                status="ready",
                summary="运行事件可实时记录与回放",
                depends_on=["harness"],
            ),
            RuntimeComponentResponse(
                id="skill_runtime",
                name="Skill Runtime",
                kind="skill",
                status="ready",
                summary=f"已登记 {skill_count} 个领域 Skill；仅已发布版本可注入运行时",
                depends_on=["harness", "memory"],
            ),
        ],
    )


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


@router.get(
    "/videos/{video_id}/semantic-events",
    response_model=SemanticEventsResponse,
    tags=["understanding"],
)
async def get_semantic_events(
    video_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> SemanticEventsResponse:
    await container.videos.get_video(video_id)
    items = list(await container.store.list_semantic_events(video_id))
    return SemanticEventsResponse(video_id=video_id, items=items)


@router.get(
    "/videos/{video_id}/narrative-context",
    response_model=NarrativeContextResponse,
    tags=["understanding"],
)
async def get_narrative_context(
    video_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> NarrativeContextResponse:
    await container.videos.get_video(video_id)
    context = await container.store.get_narrative_context(video_id)
    return NarrativeContextResponse(video_id=video_id, context=context)


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
        trace_id=payload.trace_id,
        use_web_search=payload.use_web_search,
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


@router.get(
    "/agent-runs/{run_id}/trace",
    response_model=TraceEventsResponse,
    tags=["observability"],
)
async def get_agent_trace(
    run_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> TraceEventsResponse:
    run = await container.store.get_run(run_id)
    if run is None:
        from lets_go_video_agent.application.errors import NotFoundError

        raise NotFoundError(f"未找到 Agent Run: {run_id}")
    items = list(await container.store.list_trace_events(run_id))
    return TraceEventsResponse(trace_id=run_id, items=items)


@router.get(
    "/traces/{trace_id}",
    response_model=TraceEventsResponse,
    tags=["observability"],
)
async def get_trace(
    trace_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> TraceEventsResponse:
    """读取问答或视频处理 Trace，不要求它必须对应 AgentRun。"""
    items = list(await container.store.list_trace_events(trace_id))
    return TraceEventsResponse(trace_id=trace_id, items=items)


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
