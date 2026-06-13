from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.core import contracts as c


def _login(client: TestClient, email: str = "admin@local.cutagent", password: str = "local-admin") -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _router_module():
    try:
        return importlib.import_module("apps.api.routers.creative")
    except ModuleNotFoundError as exc:
        pytest.fail(f"creative router is missing: {exc}")


def test_reference_extract_endpoint_returns_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    router = _router_module()

    async def fake_extract_reference(url: str, language: str, **kwargs: object) -> c.ReferenceExtractResult:
        assert url == "https://youtu.be/demo"
        assert language == "zh"
        assert {"asr_invoke", "object_store", "secret_store"} <= set(kwargs)
        return c.ReferenceExtractResult(
            reference_script="提取出的口播文案",
            source="subtitle",
            title="来源标题",
            platform="youtube",
            duration_sec=18.2,
            resolved_url="https://youtu.be/resolved",
        )

    monkeypatch.setattr(router, "extract_reference", fake_extract_reference)
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        response = client.post("/api/creative/reference-extract", json={"url": "https://youtu.be/demo"})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "reference_script": "提取出的口播文案",
        "source": "subtitle",
        "title": "来源标题",
        "platform": "youtube",
        "duration_sec": 18.2,
        "resolved_url": "https://youtu.be/resolved",
    }


def test_reference_extract_endpoint_requires_operator_role(monkeypatch: pytest.MonkeyPatch) -> None:
    router = _router_module()
    monkeypatch.setattr(
        router,
        "extract_reference",
        lambda *args, **kwargs: pytest.fail("viewer must be rejected before extraction"),
    )
    app = create_app()
    with TestClient(app) as client:
        _login(client, "viewer@local.cutagent", "local-viewer")
        response = client.post("/api/creative/reference-extract", json={"url": "https://youtu.be/demo"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.forbidden"


def test_reference_extract_endpoint_maps_service_error(monkeypatch: pytest.MonkeyPatch) -> None:
    router = _router_module()
    error_cls = router.ReferenceExtractError

    async def fake_extract_reference(*args: object, **kwargs: object) -> c.ReferenceExtractResult:
        raise error_cls(c.ErrorCode.reference_unreachable, "Reference URL is unreachable.")

    monkeypatch.setattr(router, "extract_reference", fake_extract_reference)
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        response = client.post("/api/creative/reference-extract", json={"url": "https://youtu.be/down"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "reference.unreachable"
