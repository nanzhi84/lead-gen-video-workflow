import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

if os.getenv("CUTAGENT_RUN_DB_TESTS") != "1":
    pytest.skip("Set CUTAGENT_RUN_DB_TESTS=1 to run database integration tests.", allow_module_level=True)

from apps.api.main import app
from packages.core.storage.bootstrap import get_sqlalchemy_session_factory_if_enabled
from packages.core.storage.database import (
    ArtifactRow,
    JobRow,
    NodeRunRow,
    OutboxEventRow,
    PromptInvocationRow,
    ProviderInvocationRow,
    PublishPackageRow,
    UsageMeterRecordRow,
    WorkflowRunRow,
)


def sqlalchemy_session_factory():
    session_factory = get_sqlalchemy_session_factory_if_enabled()
    if session_factory is None:
        pytest.skip("Set CUTAGENT_STORAGE_BACKEND=sqlalchemy to run database integration tests.")
    return session_factory


def test_sqlalchemy_workflow_job_run_report_and_artifacts_are_persisted():
    session_factory = sqlalchemy_session_factory()

    with TestClient(app) as client:
        admin_login = client.post(
            "/api/auth/login",
            json={"email": "admin@local.cutagent", "password": "local-admin"},
        )
        assert admin_login.status_code == 200, admin_login.text

        created = client.post(
            "/api/jobs/digital-human-video",
            json={
                "case_id": "case_demo",
                "title": "SQLAlchemy workflow video",
                "script": "用一个简短脚本验证数据库工作流持久化。",
                "publish_content": "Database workflow handoff.",
                "voice": {"voice_id": "voice_sandbox"},
                "portrait": {"required": True},
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        job_id = body["job"]["id"]
        run_id = body["initial_run"]["id"]
        assert body["initial_run"]["status"] in {"succeeded", "degraded"}

        job_detail = client.get(f"/api/jobs/{job_id}")
        assert job_detail.status_code == 200, job_detail.text
        assert job_detail.json()["job"]["current_run_id"] == run_id
        assert job_detail.json()["latest_report_artifact_id"]

        run_detail = client.get(f"/api/runs/{run_id}")
        assert run_detail.status_code == 200, run_detail.text
        run_body = run_detail.json()
        assert run_body["run"]["id"] == run_id
        assert len(run_body["node_runs"]) >= 10
        assert run_body["artifacts"]

        report = client.get(f"/api/runs/{run_id}/report")
        assert report.status_code == 200, report.text
        assert report.json()["public_report"]["run_id"] == run_id

        artifacts = client.get(f"/api/runs/{run_id}/artifacts")
        assert artifacts.status_code == 200, artifacts.text
        assert len(artifacts.json()["artifacts"]) == len(run_body["artifacts"])

        events = client.get(f"/api/runs/{run_id}/events")
        assert events.status_code == 200, events.text
        assert events.json()["stream_url"] == f"/api/ws/runs/{run_id}"

        finished = client.get("/api/cases/case_demo/finished-videos")
        assert finished.status_code == 200, finished.text
        assert any(item["run_id"] == run_id for item in finished.json()["items"])

        packages = client.get("/api/publish/packages")
        assert packages.status_code == 200, packages.text
        assert any(item["source_finished_video_id"] for item in packages.json()["items"])

    with session_factory() as session:
        assert session.get(JobRow, job_id) is not None
        assert session.get(WorkflowRunRow, run_id) is not None
        node_runs = list(session.scalars(select(NodeRunRow).where(NodeRunRow.run_id == run_id)))
        artifact_rows = list(session.scalars(select(ArtifactRow).where(ArtifactRow.run_id == run_id)))
        provider_rows = list(
            session.scalars(select(ProviderInvocationRow).where(ProviderInvocationRow.run_id == run_id))
        )
        provider_ids = {row.id for row in provider_rows}
        usage_rows = list(
            session.scalars(
                select(UsageMeterRecordRow).where(
                    UsageMeterRecordRow.provider_invocation_id.in_(provider_ids)
                )
            )
        )
        prompt_rows = list(
            session.scalars(select(PromptInvocationRow).where(PromptInvocationRow.run_id == run_id))
        )
        outbox_row = session.scalar(
            select(OutboxEventRow)
            .where(OutboxEventRow.topic == "workflow.run.updated")
            .where(OutboxEventRow.aggregate_id == run_id)
        )
        package_rows = list(session.scalars(select(PublishPackageRow)))
        assert len(node_runs) >= 10
        assert artifact_rows
        assert provider_rows
        assert usage_rows
        assert {row.provider_invocation_id for row in usage_rows}.issubset(provider_ids)
        assert prompt_rows
        assert any(row.provider_invocation_id in provider_ids for row in prompt_rows)
        assert outbox_row is not None
        assert outbox_row.status == "pending"
        assert outbox_row.payload["run_id"] == run_id
        assert any(row.source_finished_video_id for row in package_rows)
