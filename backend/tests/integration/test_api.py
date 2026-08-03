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


def test_agent_trace_contains_public_steps_not_chain_of_thought(client: TestClient) -> None:
    answer = client.post(
        f"/api/v1/videos/{DEMO_VIDEO_ID}/questions",
        json={"query": "视频主要讲了什么？", "target": {"kind": "global"}},
    ).json()
    trace = client.get(f"/api/v1/agent-runs/{answer['trace_id']}")
    assert trace.status_code == 200
    data = trace.json()
    assert data["status"] == "completed"
    assert data["usage"]["tool_calls"] >= 1
    assert all("thought" not in step for step in data["steps"])
