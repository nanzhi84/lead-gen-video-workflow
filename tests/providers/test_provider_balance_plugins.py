from decimal import Decimal

import httpx

from packages.ai.providers.balance import query_provider_balance
from packages.core.contracts import ProviderOptionsSchemaRef, ProviderProfile


class SecretStoreStub:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}

    def get(self, secret_ref: str) -> str | None:
        return self.values.get(secret_ref)


def profile(provider_id: str, secret_ref: str | None = "provider.secret") -> ProviderProfile:
    return ProviderProfile(
        id=f"{provider_id}.prod",
        provider_id=provider_id,
        model_id="model",
        capability="llm.chat",
        display_name=provider_id,
        environment="prod",
        secret_ref=secret_ref,
        options_schema_ref=ProviderOptionsSchemaRef(schema_id="provider.options"),
    )


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test")


def test_balance_query_marks_missing_secret_as_unconfigured_without_http_call():
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    item = query_provider_balance(
        profile("deepseek"),
        secret_store=SecretStoreStub(),
        http_client=client_for(handler),
    )

    assert item.status == "unconfigured"
    assert item.balance is None
    assert called is False


def test_balance_query_marks_minimax_as_unsupported_even_with_secret():
    item = query_provider_balance(
        profile("minimax.tts"),
        secret_store=SecretStoreStub({"provider.secret": "minimax-key"}),
        http_client=client_for(lambda _: httpx.Response(500)),
    )

    assert item.status == "unsupported"
    assert item.balance is None
    assert item.detail


def test_deepseek_balance_query_parses_cny_balance():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user/balance"
        assert request.headers["Authorization"] == "Bearer deepseek-key"
        return httpx.Response(
            200,
            json={
                "is_available": True,
                "balance_infos": [
                    {"currency": "USD", "total_balance": "2.00"},
                    {"currency": "CNY", "total_balance": "12.34"},
                ],
            },
        )

    item = query_provider_balance(
        profile("deepseek"),
        secret_store=SecretStoreStub({"provider.secret": "deepseek-key"}),
        http_client=client_for(handler),
    )

    assert item.status == "ok"
    assert item.balance is not None
    assert item.balance.amount == Decimal("12.34")
    assert item.balance.currency == "CNY"


def test_kimi_balance_query_maps_401_to_unauthorized():
    item = query_provider_balance(
        profile("kimi"),
        secret_store=SecretStoreStub({"provider.secret": "kimi-key"}),
        http_client=client_for(lambda _: httpx.Response(401)),
    )

    assert item.status == "unauthorized"
    assert item.balance is None


def test_runninghub_balance_query_maps_http_failure_to_sanitized_error():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/uc/openapi/accountStatus"
        return httpx.Response(500, text="server saw rh-key")

    item = query_provider_balance(
        profile("runninghub.heygem"),
        secret_store=SecretStoreStub({"provider.secret": "rh-key"}),
        http_client=client_for(handler),
    )

    assert item.status == "error"
    assert item.balance is None
    assert "rh-key" not in (item.detail or "")
