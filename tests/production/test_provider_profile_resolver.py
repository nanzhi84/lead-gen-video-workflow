"""Unit tests for ProviderProfileResolver (real-vs-sandbox capability gating).

These exercise the resolver in isolation — extracted from LocalRuntimeAdapter —
so its gating rules (enabled + plugin registered + non-sandbox + active secret)
are covered directly rather than only through the broader pipeline tests. The
gateway is a real in-memory ProviderGateway with mock plugins; secrets are armed
via a LocalSecretStore, matching the production gating surface.
"""

from __future__ import annotations

import pytest

from packages.ai.gateway.provider_gateway import ProviderGateway
from packages.core.contracts import (
    DigitalHumanVideoRequest,
    ErrorCode,
    ProviderOptionsSchemaRef,
    ProviderProfile,
)
from packages.core.storage.object_store import LocalObjectStore
from packages.core.storage.repository import Repository
from packages.core.storage.secret_store import LocalSecretStore
from packages.core.workflow import NodeExecutionError
from packages.production.pipeline._provider_profiles import ProviderProfileResolver


def _resolver(tmp_path):
    repository = Repository()
    secret_store = LocalSecretStore(tmp_path / "secrets")
    object_store = LocalObjectStore(tmp_path / "objects")
    gateway = ProviderGateway(
        repository,
        secret_store=secret_store,
        object_store=object_store,
        auto_register_real_plugins=False,
    )
    resolver = ProviderProfileResolver(repository, gateway)
    return resolver, repository, gateway, secret_store


def _profile(
    capability: str,
    *,
    profile_id: str,
    provider_id: str,
    enabled: bool = True,
    secret_ref: str | None = None,
) -> ProviderProfile:
    domain = capability.split(".")[0]
    return ProviderProfile(
        id=profile_id,
        provider_id=provider_id,
        model_id="real-model",
        capability=capability,
        display_name=profile_id,
        environment="prod",
        enabled=enabled,
        secret_ref=secret_ref,
        options_schema_ref=ProviderOptionsSchemaRef(schema_id=f"provider.{domain}.options"),
    )


class _ProviderReader:
    def __init__(self, profiles: list[ProviderProfile]) -> None:
        self._profiles = {profile.id: profile for profile in profiles}

    def get_profile(self, profile_id: str) -> ProviderProfile | None:
        return self._profiles.get(profile_id)

    def list_profiles(
        self,
        *,
        provider_id: str | None = None,
        capability: str | None = None,
        environment: str | None = None,
        limit: int = 200,
    ) -> list[ProviderProfile]:
        profiles = list(self._profiles.values())
        if provider_id:
            profiles = [profile for profile in profiles if profile.provider_id == provider_id]
        if capability:
            profiles = [profile for profile in profiles if profile.capability == capability]
        if environment:
            profiles = [profile for profile in profiles if profile.environment == environment]
        return profiles[:limit]

    def list_price_items(self) -> list:
        return []

    def secret_is_active(self, secret_ref: str) -> bool:
        return True


def _tts_request(*, provider_profile_id: str | None = None, voice_id: str = "voice_unbound"):
    # "voice_unbound" is intentionally NOT the seeded "voice_sandbox": it carries no
    # provider binding, so the no-binding fallback/raise path is exercised.
    voice: dict = {"voice_id": voice_id}
    if provider_profile_id is not None:
        voice["provider_profile_id"] = provider_profile_id
    return DigitalHumanVideoRequest(case_id="case_demo", script="第一句。第二句。", voice=voice)


# --------------------------------------------------------------------- tts.speech


def test_tts_no_binding_falls_back_to_sandbox_when_allowed(tmp_path):
    # conftest sets CUTAGENT_ALLOW_SANDBOX_FALLBACK=1 by default.
    resolver, *_ = _resolver(tmp_path)
    assert resolver.tts_profile_id(_tts_request()) == "sandbox.tts.default"


def test_tts_no_binding_raises_when_sandbox_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CUTAGENT_ALLOW_SANDBOX_FALLBACK", "0")
    resolver, *_ = _resolver(tmp_path)
    with pytest.raises(NodeExecutionError) as exc:
        resolver.tts_profile_id(_tts_request())
    assert exc.value.error.code == ErrorCode.provider_unsupported_option


def test_tts_explicit_armed_real_profile_returns_its_id(tmp_path):
    resolver, repository, gateway, secret_store = _resolver(tmp_path)
    repository.provider_profiles["minimax.real"] = _profile(
        "tts.speech", profile_id="minimax.real", provider_id="minimax.tts", secret_ref="minimax.secret"
    )
    gateway.plugins["minimax.tts"] = object()
    secret_store.put("minimax-key", secret_ref="minimax.secret")
    assert resolver.tts_profile_id(_tts_request(provider_profile_id="minimax.real")) == "minimax.real"


def test_tts_explicit_missing_profile_raises_even_when_sandbox_allowed(tmp_path):
    resolver, *_ = _resolver(tmp_path)
    with pytest.raises(NodeExecutionError) as exc:
        resolver.tts_profile_id(_tts_request(provider_profile_id="does.not.exist"))
    assert exc.value.error.code == ErrorCode.provider_unsupported_option


def test_tts_real_profile_without_active_secret_falls_back(tmp_path):
    resolver, repository, gateway, _ = _resolver(tmp_path)
    repository.provider_profiles["minimax.real"] = _profile(
        "tts.speech", profile_id="minimax.real", provider_id="minimax.tts", secret_ref="minimax.secret"
    )
    gateway.plugins["minimax.tts"] = object()
    # secret NOT armed -> not real -> sandbox fallback (allowed by conftest), but the
    # voice binding is explicit so the "incompatible" raise does not apply: the
    # profile resolves yet is gated off by its inactive secret.
    assert resolver.tts_profile_id(_tts_request(provider_profile_id="minimax.real")) == "sandbox.tts.default"


# ------------------------------------------------------------------- lipsync.video


def test_resolve_lipsync_real_when_armed_and_gated_without_secret(tmp_path):
    resolver, repository, gateway, secret_store = _resolver(tmp_path)
    repository.provider_profiles["heygem.real"] = _profile(
        "lipsync.video", profile_id="heygem.real", provider_id="runninghub.heygem", secret_ref="heygem.secret"
    )
    gateway.plugins["runninghub.heygem"] = object()
    request = DigitalHumanVideoRequest(
        case_id="case_demo",
        script="第一句。",
        voice={"voice_id": "voice_sandbox"},
        lipsync={"enabled": True, "provider_profile_id": "heygem.real"},
    )

    profile, is_real = resolver.resolve_lipsync(request)
    assert profile is not None and is_real is False  # secret not armed -> gated

    secret_store.put("heygem-key", secret_ref="heygem.secret")
    profile, is_real = resolver.resolve_lipsync(request)
    assert profile is not None and is_real is True


# ------------------------------------------------------------------ image.generate


def test_image_cover_profile_gated_on_active_secret(tmp_path):
    resolver, repository, gateway, secret_store = _resolver(tmp_path)
    repository.provider_profiles["openai.image.real"] = _profile(
        "image.generate", profile_id="openai.image.real", provider_id="openai.image", secret_ref="openai.image.secret"
    )
    gateway.plugins["openai.image"] = object()
    request = DigitalHumanVideoRequest(
        case_id="case_demo",
        script="第一句。",
        voice={"voice_id": "voice_sandbox"},
        cover={"mode": "ai"},
    )

    assert resolver.image_cover_profile_id(request) is None  # no active secret -> not armed

    secret_store.put("openai-image-key", secret_ref="openai.image.secret")
    assert resolver.image_cover_profile_id(request) == "openai.image.real"


def test_image_cover_profile_prefers_image2_then_seedream(tmp_path):
    resolver, repository, gateway, secret_store = _resolver(tmp_path)
    repository.provider_profiles["openai.image.real"] = _profile(
        "image.generate", profile_id="openai.image.real", provider_id="openai.image", secret_ref="openai.image.secret"
    )
    repository.provider_profiles["volcengine.seedream.real"] = _profile(
        "image.generate",
        profile_id="volcengine.seedream.real",
        provider_id="volcengine.seedream",
        secret_ref="volcengine.seedream.secret",
    )
    gateway.plugins["openai.image"] = object()
    gateway.plugins["volcengine.seedream"] = object()
    request = DigitalHumanVideoRequest(
        case_id="case_demo",
        script="第一句。",
        voice={"voice_id": "voice_sandbox"},
        cover={"mode": "ai"},
    )

    secret_store.put("ark-key", secret_ref="volcengine.seedream.secret")
    assert resolver.image_cover_profile_id(request) == "volcengine.seedream.real"
    assert resolver.image_cover_profile_ids(request) == ["volcengine.seedream.real"]

    secret_store.put("openai-image-key", secret_ref="openai.image.secret")
    assert resolver.image_cover_profile_id(request) == "openai.image.real"
    assert resolver.image_cover_profile_ids(request) == [
        "openai.image.real",
        "volcengine.seedream.real",
    ]

    explicit_seedream = request.model_copy(
        update={"cover": request.cover.model_copy(update={"template_id": "volcengine.seedream.real"})}
    )
    assert resolver.image_cover_profile_ids(explicit_seedream) == ["volcengine.seedream.real"]


def test_image_cover_profiles_can_come_from_runtime_reader(tmp_path):
    resolver, _, gateway, _ = _resolver(tmp_path)
    seedream = _profile(
        "image.generate",
        profile_id="volcengine.seedream.real",
        provider_id="volcengine.seedream",
    )
    image2 = _profile(
        "image.generate",
        profile_id="openai.image.real",
        provider_id="openai.image",
    )
    gateway.provider_reader = _ProviderReader([seedream, image2])
    gateway.plugins["openai.image"] = object()
    gateway.plugins["volcengine.seedream"] = object()
    request = DigitalHumanVideoRequest(
        case_id="case_demo",
        script="第一句。",
        voice={"voice_id": "voice_sandbox"},
        cover={"mode": "ai"},
    )

    assert resolver.image_cover_profile_ids(request) == [
        "openai.image.real",
        "volcengine.seedream.real",
    ]


# ------------------------------------------------------------------ first_available


def test_first_available_can_exclude_sandbox(tmp_path):
    resolver, repository, gateway, _ = _resolver(tmp_path)
    repository.provider_profiles["sandbox.llm"] = _profile(
        "llm.chat", profile_id="sandbox.llm", provider_id="sandbox"
    )
    repository.provider_profiles["real.llm"] = _profile(
        "llm.chat", profile_id="real.llm", provider_id="vendor.llm"
    )
    gateway.plugins["sandbox"] = object()
    gateway.plugins["vendor.llm"] = object()

    # include_sandbox=True returns the first match (sandbox), False skips it.
    assert resolver.first_available("llm.chat", include_sandbox=True).provider_id == "sandbox"
    assert resolver.first_available("llm.chat", include_sandbox=False).id == "real.llm"
