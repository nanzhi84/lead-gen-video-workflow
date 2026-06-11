from fastapi.testclient import TestClient

from apps.api.app import create_app


def login_admin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@local.cutagent", "password": "local-admin"},
    )
    assert response.status_code == 200, response.text


def test_source_binding_can_be_deleted_before_import() -> None:
    with TestClient(create_app()) as client:
        login_admin(client)
        created = client.post(
            "/api/cases/case_demo/agent/source-bindings",
            json={
                "source_type": "manual_note",
                "source_ref": "首屏先给具体成果，再讲方法。",
                "title": "R6 delete probe",
            },
        )
        assert created.status_code == 201, created.text
        binding_id = created.json()["id"]

        deleted = client.delete(f"/api/cases/case_demo/agent/source-bindings/{binding_id}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["ok"] is True

        listed = client.get("/api/cases/case_demo/agent/source-bindings")
        assert listed.status_code == 200, listed.text
        assert all(item["id"] != binding_id for item in listed.json()["items"])

        imported = client.post(
            "/api/cases/case_demo/agent/import-source",
            json={"source_binding_id": binding_id},
        )
        assert imported.status_code == 400, imported.text
        assert imported.json()["error"]["code"] == "validation.invalid_options"
