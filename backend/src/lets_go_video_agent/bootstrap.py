from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from lets_go_video_agent.agents.harness.engine import AgentHarness
from lets_go_video_agent.agents.roles.evidence_verifier import EvidenceVerifier
from lets_go_video_agent.agents.roles.qa_investigator import QAInvestigator
from lets_go_video_agent.agents.roles.skill_builder import SkillBuilderAgent
from lets_go_video_agent.agents.tools.video_tools import build_video_tool_registry
from lets_go_video_agent.application.ports import AppStore
from lets_go_video_agent.application.services import (
    QuestionService,
    VideoService,
    create_budget,
)
from lets_go_video_agent.application.skill_projects import SkillProjectService
from lets_go_video_agent.application.skill_studio import SkillPolicyValidator, SkillStudioService
from lets_go_video_agent.config import Settings
from lets_go_video_agent.fixtures import DEMO_VIDEO_ID, seed_demo
from lets_go_video_agent.infrastructure.memory import (
    InMemoryFrameInspector,
    InMemoryRetrieval,
    InMemoryStore,
)
from lets_go_video_agent.infrastructure.models.deepseek_client import (
    CostLedger,
    DeepSeekClient,
    DeepSeekPrices,
)
from lets_go_video_agent.infrastructure.models.ollama_vision_client import OllamaVisionClient
from lets_go_video_agent.infrastructure.models.siliconflow_vision_client import (
    SiliconFlowVisionClient,
)
from lets_go_video_agent.infrastructure.search.mcp_search_client import McpSearchClient
from lets_go_video_agent.infrastructure.search.searxng_client import SearxngClient
from lets_go_video_agent.media.local_pipeline import LocalProcessingManager
from lets_go_video_agent.media.local_storage import LocalUploadStore
from lets_go_video_agent.media.url_policy import SourceUrlPolicy
from lets_go_video_agent.media.video_library import organize_video_library, sync_video_library
from lets_go_video_agent.media.ytdlp import YtDlpAdapter


@dataclass(slots=True)
class Container:
    """依赖装配容器。

    `if memory/mysql` 之类的环境判断只应存在于这个装配边界。用例、Agent 与路由里
    不允许根据运行环境偷偷切换实现。
    """

    settings: Settings
    store: AppStore
    videos: VideoService
    questions: QuestionService
    skills: SkillStudioService
    skill_projects: SkillProjectService
    processing: LocalProcessingManager
    cost_ledger: CostLedger
    harness: AgentHarness
    search: McpSearchClient | SearxngClient | None

    async def startup(self) -> None:
        await self.store.ping()
        await self.cost_ledger.hydrate()
        if self.settings.seed_demo_data:
            await seed_demo(self.store)
        elif await self.store.get(DEMO_VIDEO_ID) is not None:
            # 演示夹具只服务测试/演示环境，关闭配置后自动从本地目录中移除。
            await self.store.delete(DEMO_VIDEO_ID)
        await sync_video_library(self.store, self.settings.video_library_dir)
        await organize_video_library(self.store, self.settings.video_library_dir)

    async def shutdown(self) -> None:
        await self.store.close()


def build_container(settings: Settings) -> Container:
    store: AppStore
    if settings.repository_backend == "memory":
        store = InMemoryStore(
            skill_catalog_path=settings.local_data_dir / "skills" / "catalog.json",
            state_catalog_path=settings.local_data_dir / "catalog" / "memory-state.json",
        )
    elif settings.repository_backend == "mysql":
        # 延迟导入可选依赖，使不安装 SQLAlchemy 的纯内存测试仍然可以运行。
        from lets_go_video_agent.infrastructure.persistence.mysql.repository import (
            MySqlStore,
        )

        store = MySqlStore(settings.database_url)
    else:
        raise RuntimeError(f"未知仓库后端: {settings.repository_backend}")
    retrieval = InMemoryRetrieval(store)
    verifier = EvidenceVerifier()
    cost_ledger = CostLedger(
        settings.local_data_dir / "costs" / "model-usage.jsonl",
        events=store,
        hydrate_events=settings.repository_backend == "memory",
    )
    llm = None
    if settings.llm_provider == "deepseek" and settings.llm_api_key:
        llm = DeepSeekClient(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            api_base=settings.llm_api_base or "https://api.deepseek.com",
            ledger=cost_ledger,
            prices=DeepSeekPrices(
                cache_hit_input=Decimal(str(settings.deepseek_cache_hit_price_cny_per_million)),
                cache_miss_input=Decimal(str(settings.deepseek_cache_miss_price_cny_per_million)),
                output=Decimal(str(settings.deepseek_output_price_cny_per_million)),
            ),
            proxy_url=settings.outbound_http_proxy,
        )
    investigator = QAInvestigator(llm=llm)
    skills = SkillStudioService(
        store=store,
        builder=SkillBuilderAgent(llm=llm),
        validator=SkillPolicyValidator(),
        artifact_root=settings.skill_artifact_dir,
    )
    vlm: OllamaVisionClient | SiliconFlowVisionClient | None = None
    if settings.vlm_provider == "ollama":
        vlm = OllamaVisionClient(
            model=settings.vlm_model,
            api_base=settings.vlm_api_base,
        )
    elif settings.vlm_provider == "siliconflow" and settings.vlm_api_key:
        vlm = SiliconFlowVisionClient(
            api_key=settings.vlm_api_key,
            model=settings.vlm_model,
            api_base=settings.vlm_api_base,
            ledger=cost_ledger,
            proxy_url=settings.outbound_http_proxy,
        )
    web_search: McpSearchClient | SearxngClient | None = None
    if settings.search_provider == "mcp":
        web_search = McpSearchClient(url=settings.search_mcp_url)
    elif settings.search_provider == "searxng":
        web_search = SearxngClient(api_base=settings.search_api_base)

    frame_inspector = InMemoryFrameInspector(
        retrieval,
        store=store,
        data_dir=settings.local_data_dir,
        library_dir=settings.video_library_dir,
        vlm=vlm,
        vlm_timeout_seconds=settings.frame_vlm_timeout_seconds,
    )
    tool_registry = build_video_tool_registry(
        retrieval,
        frame_inspector,
        web_search,
        frame_timeout_seconds=settings.frame_tool_timeout_seconds,
    )
    harness = AgentHarness(tool_registry, events=store)

    video_service = VideoService(
        videos=store,
        timeline=store,
        upload_store=LocalUploadStore(
            root=settings.video_library_dir,
            max_bytes=settings.max_upload_bytes,
            object_key_prefix="library",
        ),
        url_policy=SourceUrlPolicy(),
    )
    question_service = QuestionService(
        videos=store,
        answers=store,
        runs=store,
        harness=harness,
        investigator=investigator,
        verifier=verifier,
        skills=skills,
        default_budget=create_budget(
            max_model_calls=settings.agent_max_model_calls,
            max_tool_calls=settings.agent_max_tool_calls,
            max_tokens=settings.agent_max_tokens,
            max_cost_usd=settings.agent_max_cost_usd,
            deadline_seconds=settings.agent_deadline_seconds,
        ),
    )
    processing = LocalProcessingManager(
        store=store,
        data_dir=settings.local_data_dir,
        library_dir=settings.video_library_dir,
        asr_model=settings.local_asr_model,
        llm=llm,
        vlm=vlm,
        web_search=web_search,
        web_downloader=YtDlpAdapter(
            download_root=settings.video_library_dir,
            remote_enabled=settings.enable_remote_downloads,
            max_download_bytes=settings.max_upload_bytes,
            cookies_from_browser=settings.ytdlp_cookies_from_browser,
            proxy_url=settings.outbound_http_proxy,
        ),
    )
    skill_projects = SkillProjectService(
        store=store,
        videos=video_service,
        processing=processing,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        vlm_provider=settings.vlm_provider,
        vlm_model=settings.vlm_model,
    )
    return Container(
        settings=settings,
        store=store,
        videos=video_service,
        questions=question_service,
        skills=skills,
        skill_projects=skill_projects,
        processing=processing,
        cost_ledger=cost_ledger,
        harness=harness,
        search=web_search,
    )
