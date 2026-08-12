from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from lets_go_video_agent.config import Settings
from lets_go_video_agent.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        repository_backend="memory",
        seed_demo_data=True,
        local_data_dir=tmp_path / "data",
        video_library_dir=tmp_path / "videos",
        skill_artifact_dir=tmp_path / "skills" / "generated",
        llm_provider="mock",
        llm_api_key=None,
        vlm_provider="mock",
        vlm_api_key=None,
        search_provider="disabled",
        enable_remote_downloads=False,
    )
    with TestClient(create_app(settings=settings)) as test_client:
        yield test_client
