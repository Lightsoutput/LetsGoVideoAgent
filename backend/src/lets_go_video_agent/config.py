from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """所有外部配置的唯一入口。

    业务代码不直接读取环境变量。这样测试可以创建独立 Settings，部署时也能明确知道
    哪个配置影响了模型、仓库或工作流。
    """

    model_config = SettingsConfigDict(
        # 不依赖启动时的当前目录，确保从 IDE、backend/ 或项目根目录启动读取同一配置。
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"
    outbound_http_proxy: str | None = None

    repository_backend: str = "memory"
    workflow_backend: str = "inline"
    seed_demo_data: bool = True
    local_data_dir: Path = Path("./data")
    enable_remote_downloads: bool = False
    ytdlp_cookies_from_browser: str | None = None
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024

    database_url: str = "mysql+aiomysql://video_agent:change_me@localhost:3306/lets_go_video_agent"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "video_artifacts"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "change_minio_me"
    minio_bucket: str = "video-agent"
    minio_secure: bool = False

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "video-processing"

    model_profile: str = "economy"
    llm_provider: str = "mock"
    llm_model: str = "mock-evidence-model"
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    vlm_provider: str = "mock"
    vlm_model: str = "mock-vision-model"
    vlm_api_base: str = "http://127.0.0.1:11434"
    vlm_api_key: str | None = None
    search_provider: str = "disabled"
    search_api_base: str = "http://127.0.0.1:8888"
    search_mcp_host: str = "127.0.0.1"
    search_mcp_port: int = 8090
    search_mcp_url: str = "http://127.0.0.1:8090/mcp"

    # P0 默认在 CPU 上运行 small，兼顾中文准确率、下载体积与普通开发机速度。
    local_asr_model: str = "small"
    deepseek_cache_hit_price_cny_per_million: float = 0.02
    deepseek_cache_miss_price_cny_per_million: float = 1.0
    deepseek_output_price_cny_per_million: float = 2.0

    agent_max_model_calls: int = Field(default=6, ge=0)
    agent_max_tool_calls: int = Field(default=10, ge=1)
    agent_max_tokens: int = Field(default=12_000, ge=100)
    agent_max_cost_usd: float = Field(default=0.10, ge=0)
    agent_deadline_seconds: int = Field(default=60, ge=1)

    @field_validator("local_data_dir", mode="after")
    @classmethod
    def resolve_local_data_dir(cls, value: Path) -> Path:
        """相对数据目录固定基于项目根目录，不随启动命令所在目录变化。"""
        return value.resolve() if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.app_cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
