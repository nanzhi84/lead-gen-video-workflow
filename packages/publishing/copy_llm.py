"""Wiring that backs the Publishing Copy Node with a real ``llm.chat`` provider.

``copy_node.py`` stays provider-agnostic (it takes an injected ``LlmChatPort``).
This module builds that port from a ``ProviderGateway`` + the seeded
``PublishingCopy`` prompt, selecting an enabled real ``llm.chat`` ProviderProfile
with an active secret. When no real LLM is armed it returns ``None`` so the copy
node falls back to its deterministic, non-fabricated derivation.

Shared by both the production ``ExportFinishedVideo`` node (title + cover copy)
and the publish-center copy endpoints, so neither re-implements the wiring.
"""

from __future__ import annotations

from packages.ai.gateway import ProviderCall
from packages.ai.prompts.registry import PromptRegistry
from packages.core.contracts import ErrorCode
from packages.core.workflow import NodeExecutionError
from packages.publishing.copy_node import LlmChatPort, PublishCopyContext

PUBLISHING_COPY_NODE_ID = "PublishingCopy"


def _select_real_llm_profile(gateway, repository):
    """Return an enabled real ``llm.chat`` ProviderProfile with an active secret,
    or ``None``. Mirrors the gating used elsewhere (case agent / cover): sandbox
    profiles, unregistered plugins, and inactive secrets are all excluded."""
    for profile in repository.provider_profiles.values():
        if profile.capability != "llm.chat" or not profile.enabled:
            continue
        if profile.provider_id == "sandbox":
            continue
        if profile.provider_id not in gateway.plugins:
            continue
        if profile.secret_ref and not gateway._secret_is_active(profile.secret_ref):
            continue
        return profile
    return None


def build_copy_llm_chat(
    *,
    gateway,
    repository,
    prompt_registry: PromptRegistry | None = None,
    case_id: str | None = None,
    run_id: str | None = None,
    node_run_id: str | None = None,
) -> LlmChatPort | None:
    """Build an ``LlmChatPort`` for the Publishing Copy Node, or ``None`` when no
    real ``llm.chat`` provider is armed (caller then uses deterministic copy)."""
    profile = _select_real_llm_profile(gateway, repository)
    if profile is None:
        return None
    registry = prompt_registry or PromptRegistry(repository)

    def _llm_chat(*, context: PublishCopyContext) -> tuple[dict, str | None]:
        variables = {
            "case_name": context.case_name or "未指定",
            "description": context.description or "",
            "script": context.script or "",
        }
        prompt_invocation, rendered = registry.render(
            node_id=PUBLISHING_COPY_NODE_ID,
            variables=variables,
            case_id=case_id,
            provider_profile_id=profile.id,
        )
        invocation, result = gateway.invoke(
            ProviderCall(
                case_id=case_id,
                run_id=run_id,
                node_run_id=node_run_id,
                provider_profile_id=profile.id,
                capability_id="llm.chat",
                prompt_version_id=prompt_invocation.prompt_version_id,
                input={"prompt": rendered},
                idempotency_key=f"publish-copy-{run_id}" if run_id else None,
            )
        )
        if result is None or invocation.error:
            raise NodeExecutionError(
                invocation.error.code if invocation.error else ErrorCode.provider_remote_failed,
                invocation.error.message
                if invocation.error
                else "Publishing copy LLM provider failed.",
            )
        return result.output, invocation.id

    return _llm_chat
