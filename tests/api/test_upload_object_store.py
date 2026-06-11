import hashlib

from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


def login_admin():
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@local.cutagent", "password": "local-admin"},
    )
    assert response.status_code == 200, response.text


def test_upload_flow_uses_object_store_uri_and_validates_integrity():
    login_admin()
    content = b"cutagent object store"
    digest = hashlib.sha256(content).hexdigest()
    prepared = client.post(
        "/api/uploads/prepare",
        json={
            "kind": "portrait",
            "case_id": "case_demo",
            "filename": "sample.txt",
            "content_type": "text/plain",
            "size_bytes": len(content),
            "sha256": digest,
        },
    )
    assert prepared.status_code == 201, prepared.text
    upload = prepared.json()
    assert upload["object_uri"].startswith("local://")
    assert upload["upload_url"].startswith("local://")

    uploaded = client.put(
        f"/api/uploads/{upload['id']}/file",
        files={"file": ("sample.txt", content, "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["status"] == "uploading"

    completed = client.post(
        "/api/uploads/complete",
        json={"upload_session_id": upload["id"], "size_bytes": len(content), "sha256": digest},
    )
    assert completed.status_code == 200, completed.text
    artifact = completed.json()["artifact"]
    assert artifact["kind"] == "uploaded.file"
    assert completed.json()["media_asset"]["kind"] == "portrait"
    assert completed.json()["media_asset"]["source_artifact_id"] == artifact["artifact_id"]


def test_upload_file_rejects_size_mismatch_before_completion():
    login_admin()
    prepared = client.post(
        "/api/uploads/prepare",
        json={
            "kind": "broll",
            "filename": "short.txt",
            "content_type": "text/plain",
            "size_bytes": 100,
        },
    ).json()
    response = client.put(
        f"/api/uploads/{prepared['id']}/file",
        files={"file": ("short.txt", b"short", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "upload.size_mismatch"


def test_publish_video_upload_creates_publish_package():
    login_admin()
    content = b"publish video upload"
    digest = hashlib.sha256(content).hexdigest()
    prepared = client.post(
        "/api/uploads/prepare",
        json={
            "kind": "publish_video",
            "case_id": "case_demo",
            "filename": "publish.mp4",
            "content_type": "video/mp4",
            "size_bytes": len(content),
            "sha256": digest,
        },
    )
    assert prepared.status_code == 201, prepared.text
    upload = prepared.json()
    uploaded = client.put(
        f"/api/uploads/{upload['id']}/file",
        files={"file": ("publish.mp4", content, "video/mp4")},
    )
    assert uploaded.status_code == 200, uploaded.text

    completed = client.post(
        "/api/uploads/complete",
        json={
            "upload_session_id": upload["id"],
            "sha256": digest,
            "metadata": {"title": "Publish upload"},
        },
    )

    assert completed.status_code == 200, completed.text
    assert completed.json()["media_asset"] is None
    assert completed.json()["publish_package"]["upload_artifact_id"] == completed.json()["artifact"]["artifact_id"]
    assert completed.json()["publish_package"]["platform_defaults"]["title"] == "Publish upload"
