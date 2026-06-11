from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.core import contracts as c
from packages.core.storage.repository import new_id


def _login_admin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@local.cutagent", "password": "local-admin"},
    )
    assert response.status_code == 200, response.text


def _publish_batch_for_case(app, case_id: str) -> c.PublishBatchVm:
    package = c.PublishPackage(
        id=new_id("pkg"),
        case_id=case_id,
        video_artifact=c.ArtifactRef(
            artifact_id=new_id("art"),
            kind=c.ArtifactKind.video_final,
            uri=f"local://cutagent-local/{case_id}/final.mp4",
            schema_version="artifact.ref.v1",
        ),
        platform_defaults=c.PublishDefaults(title=f"{case_id} package"),
    )
    item = c.PublishBatchItemVm(
        id=new_id("pub_item"),
        publish_package_id=package.id,
        platform="douyin",
        title=package.platform_defaults.title,
    )
    batch = c.PublishBatchVm(id=new_id("pub_batch"), items=[item])
    app.state.repository.publish_packages[package.id] = package
    app.state.repository.publish_batches[batch.id] = batch
    return batch


def test_publish_batches_query_filters_by_case_id() -> None:
    app = create_app()
    with TestClient(app) as client:
        _login_admin(client)
        demo_batch = _publish_batch_for_case(app, "case_demo")
        other_batch = _publish_batch_for_case(app, "case_other")

        all_batches = client.get("/api/publish/batches")
        assert all_batches.status_code == 200, all_batches.text
        assert {item["id"] for item in all_batches.json()["items"]} >= {
            demo_batch.id,
            other_batch.id,
        }

        filtered = client.get("/api/publish/batches", params={"case_id": "case_demo"})
        assert filtered.status_code == 200, filtered.text

    assert [item["id"] for item in filtered.json()["items"]] == [demo_batch.id]
