from uuid import uuid4

from fastapi.testclient import TestClient

from lets_go_video_agent.fixtures import DEMO_VIDEO_ID


def test_health_and_demo_video(client: TestClient) -> None:
    assert client.get("/api/v1/health/live").json()["status"] == "ok"
    response = client.get("/api/v1/videos")
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == str(DEMO_VIDEO_ID)


def test_ssrf_private_address_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/videos/imports",
        json={"url": "http://127.0.0.1/private.mp4", "rights_confirmed": True},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "unsafe_source_url"


def test_public_bilibili_url_can_be_registered_metadata_only(client: TestClient) -> None:
    response = client.post(
        "/api/v1/videos/imports",
        json={
            "url": "https://www.bilibili.com/video/BV1g441147Lc/",
            "title": "人工评测候选",
            "rights_confirmed": False,
        },
    )
    assert response.status_code == 202
    data = response.json()
    assert data["source"]["kind"] == "web"
    assert data["current_stage"] == "metadata_only_waiting_for_rights_confirmation"

    repeated = client.post(
        "/api/v1/videos/imports",
        json={
            "url": "https://www.bilibili.com/video/BV1g441147Lc/?from=another-page",
            "rights_confirmed": False,
        },
    )
    assert repeated.status_code == 202
    assert repeated.json()["id"] == data["id"]


def test_confirmed_web_import_creates_processing_run(client: TestClient) -> None:
    response = client.post(
        "/api/v1/videos/imports",
        json={
            "url": "https://www.bilibili.com/video/BV1g441147Lc/",
            "rights_confirmed": True,
        },
    )
    assert response.status_code == 202
    video_id = response.json()["id"]
    run = client.get(f"/api/v1/videos/{video_id}/processing")
    assert run.status_code == 200
    assert run.json()["video_id"] == video_id


def test_global_range_moment_and_frame_questions(client: TestClient) -> None:
    cases = [
        ("global", {"kind": "global"}),
        ("range", {"kind": "range", "time_range": {"start_ms": 60_000, "end_ms": 110_000}}),
        ("moment", {"kind": "moment", "timestamp_ms": 70_000, "context_window_ms": 10_000}),
        ("frame", {"kind": "frame", "timestamp_ms": 70_000}),
    ]
    for label, target in cases:
        response = client.post(
            f"/api/v1/videos/{DEMO_VIDEO_ID}/questions",
            json={"query": f"测试 {label} 范围发生了什么", "target": target},
        )
        assert response.status_code == 200, response.text
        answer = response.json()
        assert answer["status"] == "answered"
        assert answer["citations"]
        assert answer["trace_id"]

    frame_answer = response.json()
    assert any(item["snapshot_url"] for item in frame_answer["citations"])


def test_forced_web_answer_fails_clearly_when_search_mcp_is_disabled(
    client: TestClient,
) -> None:
    response = client.post(
        f"/api/v1/videos/{DEMO_VIDEO_ID}/questions",
        json={
            "query": "联网补充这个概念的最新背景",
            "target": {"kind": "global"},
            "use_web_search": True,
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "external_service_unavailable"
    assert "Search MCP" in response.json()["detail"]


def test_agent_trace_contains_public_steps_not_chain_of_thought(client: TestClient) -> None:
    requested_trace_id = str(uuid4())
    answer = client.post(
        f"/api/v1/videos/{DEMO_VIDEO_ID}/questions",
        json={
            "query": "视频主要讲了什么？",
            "target": {"kind": "global"},
            "trace_id": requested_trace_id,
        },
    ).json()
    assert answer["trace_id"] == requested_trace_id
    trace = client.get(f"/api/v1/agent-runs/{answer['trace_id']}")
    assert trace.status_code == 200
    data = trace.json()
    assert data["status"] == "completed"
    assert data["usage"]["tool_calls"] >= 1
    assert all("thought" not in step for step in data["steps"])

    events = client.get(f"/api/v1/agent-runs/{answer['trace_id']}/trace")
    assert events.status_code == 200
    event_items = events.json()["items"]
    assert event_items[0]["event_type"] == "agent.started"
    assert event_items[-1]["event_type"] == "workflow.completed"
    assert any(item["event_type"] == "tool.called" for item in event_items)
    assert all("prompt" not in item["attributes"] for item in event_items)

    unified_events = client.get(f"/api/v1/traces/{answer['trace_id']}")
    assert unified_events.status_code == 200
    assert unified_events.json()["items"] == event_items


def test_v1_understanding_and_usage_read_models_are_available(client: TestClient) -> None:
    semantic = client.get(f"/api/v1/videos/{DEMO_VIDEO_ID}/semantic-events")
    narrative = client.get(f"/api/v1/videos/{DEMO_VIDEO_ID}/narrative-context")
    usage = client.get("/api/v1/observability/usage")

    assert semantic.status_code == 200
    assert semantic.json() == {"video_id": str(DEMO_VIDEO_ID), "items": []}
    assert narrative.status_code == 200
    assert narrative.json() == {"video_id": str(DEMO_VIDEO_ID), "context": None}
    assert usage.status_code == 200
    assert usage.json()["call_count"] == 0
    assert usage.json()["total_cost_cny"] == "0"


def test_p1_system_observability_exposes_safe_harness_and_mcp_status(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/observability/system")

    assert response.status_code == 200
    data = response.json()
    assert data["harness"]["max_steps"] >= 1
    assert data["harness"]["registered_tools"] == ["inspect_frame", "search_timeline"]
    assert data["mcp"]["status"] == "disabled"
    assert data["repository"] == "memory"
    assert all(route["configured"] for route in data["models"])
    assert "api_key" not in response.text.lower()


def test_skill_studio_publish_binding_and_runtime_trace(client: TestClient) -> None:
    generated = client.post(
        "/api/v1/skills/generate",
        json={
            "video_ids": [str(DEMO_VIDEO_ID)],
            "goal": "理解游戏攻略的步骤、画面状态和专业术语",
            "display_name": "游戏攻略理解",
        },
    )
    assert generated.status_code == 201, generated.text
    detail = generated.json()
    skill_id = detail["skill"]["id"]
    version = detail["versions"][0]
    assert version["status"] == "draft"
    assert version["validation"]["valid"] is True

    published = client.post(f"/api/v1/skills/{skill_id}/versions/1/publish")
    assert published.status_code == 200, published.text
    assert published.json()["skill"]["active_version"] == 1

    bound = client.post(
        f"/api/v1/skills/{skill_id}/bindings",
        json={"video_ids": [str(DEMO_VIDEO_ID)]},
    )
    assert bound.status_code == 200
    assert str(DEMO_VIDEO_ID) in bound.json()["bound_video_ids"]

    answer = client.post(
        f"/api/v1/videos/{DEMO_VIDEO_ID}/questions",
        json={"query": "这类攻略应该怎样理解？", "target": {"kind": "global"}},
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["skill_name"] == "游戏攻略理解"
    trace = client.get(f"/api/v1/traces/{answer.json()['trace_id']}").json()["items"]
    assert any(item["event_type"] == "skill.loaded" for item in trace)
    assert any(item["event_type"] == "skill.validated" for item in trace)


def test_skill_can_regenerate_from_selected_samples(client: TestClient) -> None:
    generated = client.post(
        "/api/v1/skills/generate",
        json={
            "video_ids": [str(DEMO_VIDEO_ID)],
            "goal": "验证类别内容、画面与叙事规律",
            "display_name": "重生成测试 Skill",
        },
    )
    assert generated.status_code == 201, generated.text
    detail = generated.json()
    skill_id = detail["skill"]["id"]
    regenerated = client.post(
        f"/api/v1/skills/{skill_id}/regenerate",
        json={"video_ids": [str(DEMO_VIDEO_ID)]},
    )
    assert regenerated.status_code == 201, regenerated.text
    versions = regenerated.json()["versions"]
    assert versions[0]["version"] == 2
    assert versions[0]["parent_version"] == 1
    assert versions[0]["sample_video_ids"] == [str(DEMO_VIDEO_ID)]


def test_skill_batch_delete_removes_selected_skills(client: TestClient) -> None:
    skill_ids = []
    for name in ("批量删除一", "批量删除二"):
        generated = client.post(
            "/api/v1/skills/generate",
            json={
                "video_ids": [str(DEMO_VIDEO_ID)],
                "goal": "验证 Skill 批量删除接口",
                "display_name": name,
            },
        )
        assert generated.status_code == 201, generated.text
        skill_ids.append(generated.json()["skill"]["id"])

    deleted = client.post(
        "/api/v1/skills/batch-delete",
        json={"skill_ids": skill_ids},
    )
    assert deleted.status_code == 204, deleted.text
    listed_ids = {
        item["id"] for item in client.get("/api/v1/skills").json()["items"]
    }
    assert not listed_ids.intersection(skill_ids)


def test_skill_project_accepts_multiple_urls_and_exposes_team_workspace(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/skill-projects",
        json={
            "name": "Zc故事",
            "goal": "理解故事视频的叙事结构、人物关系和画面线索",
            "description": "用于积累同类视频样本",
        },
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["project"]["id"]

    added = client.post(
        f"/api/v1/skill-projects/{project_id}/videos",
        json={
            "urls": [
                "https://www.bilibili.com/video/BV1g441147Lc/",
                "https://www.bilibili.com/video/BV1xx411c7mD/",
            ],
            "rights_confirmed": False,
        },
    )
    assert added.status_code == 202, added.text
    workspace = added.json()
    assert len(workspace["items"]) == 2
    assert len(workspace["agents"]) >= 7
    assert all(item["status"] == "importing" for item in workspace["items"])

    listed = client.get("/api/v1/skill-projects")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["name"] == "Zc故事"
