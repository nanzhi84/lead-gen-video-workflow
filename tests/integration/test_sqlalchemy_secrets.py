import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

if os.getenv("CUTAGENT_RUN_DB_TESTS") != "1":
    pytest.skip("Set CUTAGENT_RUN_DB_TESTS=1 to run database integration tests.", allow_module_level=True)

from apps.api.main import app
from packages.core.storage.bootstrap import get_sqlalchemy_session_factory_if_enabled
from packages.core.storage.database import SecretRow


def sqlalchemy_session_factory():
    session_factory = get_sqlalchemy_session_factory_if_enabled()
    if session_factory is None:
        pytest.skip("Set CUTAGENT_STORAGE_BACKEND=sqlalchemy to run database integration tests.")
    return session_factory


def test_sqlalchemy_secret_create_rotate_disable_flow_is_persisted_without_plaintext():
    session_factory = sqlalchemy_session_factory()
    suffix = uuid4().hex[:8]

    with TestClient(app) as client:
        admin_login = client.post(
            "/api/auth/login",
            json={"email": "admin@local.cutagent", "password": "local-admin"},
        )
        assert admin_login.status_code == 200, admin_login.text

        created = client.post(
            "/api/secrets",
            json={
                "provider_id": f"sandbox-{suffix}",
                "environment": "local",
                "name": "API key",
                "value": "first-secret-value",
            },
        )
        assert created.status_code == 201, created.text
        secret = created.json()
        assert secret["masked_value"] == "********"
        assert secret["status"] == "active"

        with session_factory() as session:
            row = session.get(SecretRow, secret["id"])
            assert row is not None
            first_digest = row.encrypted_value
            assert first_digest is not None
            assert "first-secret-value" not in first_digest

        rotated = client.post(
            f"/api/secrets/{secret['id']}/rotate",
            json={"value": "second-secret-value", "reason": "integration rotation"},
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["masked_value"] == "********"

        disabled = client.patch(
            f"/api/secrets/{secret['id']}/disable",
            json={"reason": "integration disable"},
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["status"] == "disabled"

        listed = client.get("/api/secrets")
        assert listed.status_code == 200, listed.text
        assert any(item["id"] == secret["id"] for item in listed.json()["items"])

    with session_factory() as session:
        row = session.get(SecretRow, secret["id"])
        assert row is not None
        assert row.status == "disabled"
        assert row.encrypted_value != first_digest
        assert "second-secret-value" not in row.encrypted_value
        assert row.rotated_at is not None
