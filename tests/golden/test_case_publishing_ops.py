from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


def test_case_reflection_memory_approval_and_publish_flow():
    login = client.post(
        "/api/auth/login",
        json={"email": "admin@local.cutagent", "password": "local-admin"},
    )
    assert login.status_code == 200, login.text
    reflection = client.post(
        "/api/cases/case_demo/reflection-runs",
        json={"window": "7d", "force": True},
    )
    assert reflection.status_code == 202, reflection.text
    proposals = client.get("/api/cases/case_demo/agent/memory-proposals").json()["items"]
    assert proposals
    memory = client.post(
        f"/api/cases/case_demo/memory/{proposals[-1]['id']}/approve",
        json={"reason": "golden approval"},
    ).json()
    assert memory["status"] == "active"

    videos = client.get("/api/cases/case_demo/finished-videos").json()["items"]
    if not videos:
        client.post(
            "/api/jobs/digital-human-video",
            json={
                "case_id": "case_demo",
                "title": "Publishing seed",
                "script": "用一个简短脚本补齐发布测试。",
                "voice": {"voice_id": "voice_sandbox"},
                "portrait": {"required": True},
            },
        )
        videos = client.get("/api/cases/case_demo/finished-videos").json()["items"]
    package = client.post(
        "/api/publish/packages",
        json={"source_finished_video_id": videos[-1]["id"], "title": "Publish me", "description": ""},
    ).json()
    batch = client.post(
        "/api/publish/batches",
        json={"publish_package_ids": [package["id"]], "platform_targets": ["xiaovmao"]},
    ).json()
    submitted = client.post(f"/api/publish/batches/{batch['id']}/submit", json={"dry_run": False}).json()
    assert submitted["status"] == "completed"
    assert submitted["items"][0]["status"] == "published"

    ops = client.get("/api/ops/dashboard").json()
    assert "usage" in ops
    assert "yield_funnel" in ops
