from packages.ai.gateway.provider_gateway import ProviderCall, ProviderGateway
from packages.core.contracts import (
    ErrorCode,
    ProviderOptionsSchemaRef,
    ProviderProfile,
    ProviderStatus,
)
from packages.core.storage.repository import Repository


def gateway() -> tuple[Repository, ProviderGateway]:
    repository = Repository()
    return repository, ProviderGateway(repository)


def test_provider_capability_schema_is_registered():
    repository, _ = gateway()
    capabilities = {(item.provider_id, item.capability_id) for item in repository.provider_capabilities.values()}
    assert ("sandbox", "tts") in capabilities
    assert ("sandbox", "lipsync") in capabilities
    assert ("sandbox", "llm") in capabilities


def test_provider_option_validation_rejects_capability_mismatch():
    _, gw = gateway()
    invocation, result = gw.invoke(
        ProviderCall(
            provider_profile_id="sandbox.tts.default",
            capability_id="lipsync",
            input={},
        )
    )
    assert result is None
    assert invocation.error
    assert invocation.error.code == ErrorCode.provider_unsupported_option


def test_provider_secret_missing_is_auth_failure():
    repository, gw = gateway()
    profile = ProviderProfile(
        id="sandbox.secret.tts",
        provider_id="sandbox",
        model_id="tts.local",
        capability="tts",
        display_name="Secret TTS",
        environment="local",
        secret_ref="missing_secret",
        options_schema_ref=ProviderOptionsSchemaRef(schema_id="provider.tts.options"),
    )
    repository.provider_profiles[profile.id] = profile
    invocation, result = gw.invoke(
        ProviderCall(provider_profile_id=profile.id, capability_id="tts", input={"text": "hello"})
    )
    assert result is None
    assert invocation.error
    assert invocation.error.code == ErrorCode.provider_auth_failed


def test_provider_quota_timeout_and_remote_failed_are_reported():
    _, gw = gateway()
    expected = {
        "quota_exceeded": ErrorCode.provider_quota_exceeded,
        "timeout": ErrorCode.provider_timeout,
        "remote_failed": ErrorCode.provider_remote_failed,
    }
    for simulate, code in expected.items():
        invocation, result = gw.invoke(
            ProviderCall(
                provider_profile_id="sandbox.tts.default",
                capability_id="tts",
                input={"text": "hello", "simulate": simulate},
            )
        )
        assert result is None
        assert invocation.error
        assert invocation.error.code == code


def test_provider_cost_unpriced_is_recorded_without_blocking_result():
    repository, gw = gateway()
    repository.price_items.clear()
    invocation, result = gw.invoke(
        ProviderCall(
            provider_profile_id="sandbox.tts.default",
            capability_id="tts",
            input={"text": "hello"},
        )
    )
    assert result is not None
    assert invocation.status == ProviderStatus.cost_unpriced
    usage = next(item for item in repository.usage_records.values() if item.provider_invocation_id == invocation.id)
    assert usage.cost_unpriced is True
    assert any(alert.code == "provider.cost_unpriced" for alert in repository.alerts.values())

