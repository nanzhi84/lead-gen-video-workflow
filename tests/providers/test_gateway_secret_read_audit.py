from __future__ import annotations

import pytest

from packages.ai.gateway.provider_context import ProviderInvocationContext
from packages.ai.gateway.provider_gateway import (
    ProviderCall,
    ProviderGateway,
    ProviderResult,
)
from packages.core.contracts import ProviderOptionsSchemaRef, ProviderProfile
from packages.core.storage.object_store import LocalObjectStore
from packages.core.storage.repository import Repository
from packages.core.storage.secret_store import LocalSecretStore

PLAINTEXT = "live-reveal-secret-value-123"


def _profile(secret_ref: str | None) -> ProviderProfile:
    return ProviderProfile(
        id="provider.profile",
        provider_id="acme",
        model_id="model",
        capability="tts.speech",
        display_name="Provider",
        environment="prod",
        secret_ref=secret_ref,
        options_schema_ref=ProviderOptionsSchemaRef(schema_id="provider.tts.options"),
    )


def _context(tmp_path, *, secret_ref, secret_store, audit_sink=None, repository=None):
    return ProviderInvocationContext(
        repository=repository or Repository(),
        profile=_profile(secret_ref),
        invocation_id="pinv_1",
        secret_store=secret_store,
        object_store=LocalObjectStore(tmp_path / "objects", bucket="cutagent-ephemeral"),
        audit_sink=audit_sink,
    )


def _read_events(repository: Repository) -> list:
    return [
        event
        for event in repository.audit_events.values()
        if getattr(event, "action", None) == "secret.read"
    ]


def test_live_reveal_records_secret_read_audit_in_memory(tmp_path):
    # In-memory backend: get_secret() reveals the value AND records a secret.read
    # audit onto the runtime repository (the same store ops.audit_events reads).
    store = LocalSecretStore(root=tmp_path / "secrets")
    secret_ref = store.put(PLAINTEXT, secret_ref="acme.secret")
    repository = Repository()
    context = _context(tmp_path, secret_ref=secret_ref, secret_store=store, repository=repository)

    value = context.get_secret()

    assert value == PLAINTEXT
    events = _read_events(repository)
    assert len(events) == 1, "expected exactly one secret.read audit event"
    event = events[0]
    assert event.resource_type == "secret"
    assert event.resource_id == secret_ref
    assert event.actor == "acme"  # falls back to provider_id; no end-user in worker
    assert event.details["secret_ref"] == secret_ref
    assert event.details["provider_id"] == "acme"
    assert event.details["environment"] == "prod"
    # The plaintext value must never appear anywhere in the audit record.
    assert PLAINTEXT not in repr(event)


def test_live_reveal_routes_to_durable_audit_sink_when_present(tmp_path):
    # DB-backed deployment: the gateway wires a durable sink so a worker-process
    # reveal persists to the audit table rather than the ephemeral repository.
    store = LocalSecretStore(root=tmp_path / "secrets")
    secret_ref = store.put(PLAINTEXT, secret_ref="acme.secret")
    sink_calls: list[dict] = []

    def sink(**kwargs):
        sink_calls.append(kwargs)

    repository = Repository()
    context = _context(
        tmp_path,
        secret_ref=secret_ref,
        secret_store=store,
        audit_sink=sink,
        repository=repository,
    )

    value = context.get_secret()

    assert value == PLAINTEXT
    assert len(sink_calls) == 1
    call = sink_calls[0]
    assert call["action"] == "secret.read"
    assert call["resource_type"] == "secret"
    assert call["resource_id"] == secret_ref
    assert call["actor"] == "acme"
    assert call["details"]["secret_ref"] == secret_ref
    assert call["details"]["provider_id"] == "acme"
    assert call["details"]["environment"] == "prod"
    assert PLAINTEXT not in repr(call)
    # When a durable sink handles the audit, the in-memory log is NOT also written.
    assert _read_events(repository) == []


def test_audit_failure_does_not_kill_the_reveal(tmp_path, caplog):
    # Spec §32.9 is intentionally relaxed to best-effort on the hot read path:
    # an audit hiccup logs + swallows but still returns the secret value so the
    # provider call survives.
    store = LocalSecretStore(root=tmp_path / "secrets")
    secret_ref = store.put(PLAINTEXT, secret_ref="acme.secret")

    def failing_sink(**_kwargs):
        raise RuntimeError("audit backend down")

    context = _context(tmp_path, secret_ref=secret_ref, secret_store=store, audit_sink=failing_sink)

    value = context.get_secret()

    assert value == PLAINTEXT  # availability preserved despite audit failure
    assert any("secret.read audit failed" in rec.message for rec in caplog.records)


def test_no_audit_when_secret_ref_is_none(tmp_path):
    store = LocalSecretStore(root=tmp_path / "secrets")
    repository = Repository()
    context = _context(tmp_path, secret_ref=None, secret_store=store, repository=repository)

    assert context.get_secret() is None
    assert _read_events(repository) == []


def test_no_audit_when_backing_value_missing(tmp_path):
    # secret_ref set but the value was never stored / was disabled: no reveal,
    # therefore no secret.read audit.
    store = LocalSecretStore(root=tmp_path / "secrets")
    repository = Repository()
    context = _context(
        tmp_path, secret_ref="acme.missing", secret_store=store, repository=repository
    )

    assert context.get_secret() is None
    assert _read_events(repository) == []


class _SecretReadingPlugin:
    provider_id = "acme"

    def invoke_with_context(self, call: ProviderCall, context) -> ProviderResult:
        # Exercise the LIVE reveal seam the way real plugins do.
        self.revealed = context.get_secret()
        return ProviderResult(output={"ok": True})


def test_gateway_end_to_end_reveal_is_audited(tmp_path):
    # Drive the full ProviderGateway.invoke() path (in-memory backend) and confirm
    # a plugin's context.get_secret() reveal produces a persisted secret.read audit.
    repository = Repository()
    store = LocalSecretStore(root=tmp_path / "secrets")
    secret_ref = store.put(PLAINTEXT, secret_ref="acme.secret")
    profile = _profile(secret_ref)
    repository.provider_profiles[profile.id] = profile

    gateway = ProviderGateway(
        repository,
        secret_store=store,
        object_store=LocalObjectStore(tmp_path / "objects", bucket="cutagent-ephemeral"),
        auto_register_real_plugins=False,
    )
    plugin = _SecretReadingPlugin()
    gateway.register(plugin)

    invocation, result = gateway.invoke(
        ProviderCall(provider_profile_id=profile.id, capability_id="tts.speech")
    )

    assert result is not None
    assert plugin.revealed == PLAINTEXT
    events = _read_events(repository)
    assert len(events) == 1
    assert events[0].action == "secret.read"
    assert events[0].details["provider_id"] == "acme"
    assert PLAINTEXT not in repr(events[0])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
