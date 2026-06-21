"""Contract tests for the central infra Settings (packages.core.config).

These pin the built-in defaults (which must equal the defaults the previous
scattered os.getenv calls used) and the env-override / call-time-read semantics
that the rest of the codebase relies on.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from packages.core.config import build_settings

# Every infra env var Settings reads — cleared so we observe the built-in
# defaults rather than whatever the surrounding process/conftest exported.
_INFRA_ENV_VARS = (
    "CUTAGENT_STORAGE_BACKEND",
    "CUTAGENT_DATABASE_URL",
    "CUTAGENT_OBJECTSTORE_TIERED",
    "CUTAGENT_OBJECTSTORE_BACKEND",
    "CUTAGENT_OBJECTSTORE_BUCKET",
    "CUTAGENT_LOCAL_OBJECTSTORE_PATH",
    "CUTAGENT_OBJECTSTORE_ENDPOINT",
    "CUTAGENT_OBJECTSTORE_ACCESS_KEY",
    "CUTAGENT_OBJECTSTORE_SECRET_KEY",
    "CUTAGENT_OBJECTSTORE_REGION",
    "CUTAGENT_OBJECTSTORE_ADDRESSING_STYLE",
    "CUTAGENT_OBJECTSTORE_MULTIPART_THRESHOLD_MB",
    "CUTAGENT_OBJECTSTORE_MULTIPART_CHUNK_MB",
    "CUTAGENT_OBJECTSTORE_MAX_CONCURRENCY",
    "CUTAGENT_OBJECTSTORE_CONNECT_TIMEOUT",
    "CUTAGENT_OBJECTSTORE_READ_TIMEOUT",
    "CUTAGENT_OBJECTSTORE_MAX_ATTEMPTS",
    "CUTAGENT_EPHEMERAL_OBJECTSTORE_BACKEND",
    "CUTAGENT_EPHEMERAL_OBJECTSTORE_BUCKET",
    "CUTAGENT_OBJECTSTORE_EPHEMERAL_PATH",
    "CUTAGENT_EPHEMERAL_OBJECTSTORE_ENDPOINT",
    "CUTAGENT_EPHEMERAL_OBJECTSTORE_ACCESS_KEY",
    "CUTAGENT_EPHEMERAL_OBJECTSTORE_SECRET_KEY",
    "CUTAGENT_EPHEMERAL_OBJECTSTORE_REGION",
    "CUTAGENT_EPHEMERAL_OBJECTSTORE_ADDRESSING_STYLE",
    "CUTAGENT_WORKFLOW_RUNTIME",
    "CUTAGENT_TEMPORAL_ADDRESS",
    "CUTAGENT_TEMPORAL_NAMESPACE",
    "CUTAGENT_TEMPORAL_TASK_QUEUE",
    "CUTAGENT_REGISTRATION_OPEN",
    "CUTAGENT_REGISTRATION_CODE_SALT",
    "CUTAGENT_SECRET_STORE_DIR",
    "CUTAGENT_FFMPEG_BIN",
    "CUTAGENT_FFPROBE_BIN",
    "CUTAGENT_DISABLE_BACKGROUND_DISPATCHER",
    "CUTAGENT_PROVIDER_MAX_INFLIGHT",
    "CUTAGENT_PROVIDER_MAX_QPS",
    "CUTAGENT_PROVIDER_CIRCUIT_BREAKER",
    "CUTAGENT_PROVIDER_CIRCUIT_ERROR_RATE",
    "CUTAGENT_PROVIDER_CIRCUIT_WINDOW",
    "CUTAGENT_ALLOWED_API_HOSTS",
    "CUTAGENT_ENFORCE_PROVIDER_HOST_ALLOWLIST",
    "CUTAGENT_XIAOVMAO_CDP_HOST",
    "CUTAGENT_XIAOVMAO_CDP_PORT",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _INFRA_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_settings_built_in_defaults(clean_env) -> None:
    settings = build_settings()

    assert settings.storage.backend == "sqlalchemy"
    assert settings.storage.database_url is None

    obj = settings.object_store
    assert obj.tiered is True
    assert obj.backend == "local"
    assert obj.bucket == "cutagent-local"
    assert obj.local_path == ".data/objectstore"
    assert obj.s3.endpoint_url == "http://127.0.0.1:9000"
    assert obj.s3.access_key == ""
    assert obj.s3.secret_key == ""
    assert obj.s3.region_name == "us-east-1"
    assert obj.s3.addressing_style == "path"
    assert obj.s3.multipart_threshold_mb == 8
    assert obj.s3.multipart_chunk_mb == 8
    assert obj.s3.max_concurrency == 4
    assert obj.s3.connect_timeout == 10
    assert obj.s3.read_timeout == 120
    assert obj.s3.max_attempts == 5

    eph = obj.ephemeral
    assert eph.backend == "local"
    assert eph.bucket == "cutagent-ephemeral"
    assert eph.local_path == str(Path(tempfile.gettempdir()) / "cutagent-ephemeral")
    assert eph.endpoint_url == "http://127.0.0.1:9000"
    assert eph.region_name == "us-east-1"
    assert eph.addressing_style == "path"

    assert settings.workflow.runtime == "local"
    assert settings.workflow.temporal_address == "127.0.0.1:7233"
    assert settings.workflow.temporal_namespace == "default"
    assert settings.workflow.temporal_task_queue == "cutagent-production"

    assert settings.auth.registration_open is True
    assert settings.auth.registration_code_salt == "local-dev-registration-code-salt"

    assert settings.secret_store.dir == ".data/secrets"
    assert settings.media.ffmpeg_bin is None
    assert settings.media.ffprobe_bin is None
    assert settings.api.disable_background_dispatcher is False

    # Provider gateway knobs (consolidated from packages/ai + packages/ops): these
    # defaults must equal the previous scattered os.getenv defaults byte-for-byte.
    prov = settings.providers
    assert prov.max_inflight == 4
    assert prov.max_qps == 4
    assert prov.circuit_breaker_enabled is False
    assert prov.circuit_error_rate_threshold == 0.5
    assert prov.circuit_window_hours == 24
    assert prov.allowed_api_hosts == ""
    assert prov.enforce_host_allowlist is False

    # Publishing 小V猫 CDP endpoint (consolidated from apps/api + packages/publishing).
    assert settings.publishing.xiaovmao_cdp_host == "127.0.0.1"
    assert settings.publishing.xiaovmao_cdp_port == 9222


def test_settings_reads_env_overrides(clean_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTAGENT_STORAGE_BACKEND", "MEMORY")  # lower-cased
    monkeypatch.setenv("CUTAGENT_DATABASE_URL", "postgresql+psycopg://x/db")
    monkeypatch.setenv("CUTAGENT_OBJECTSTORE_TIERED", "0")
    monkeypatch.setenv("CUTAGENT_OBJECTSTORE_BACKEND", "S3")  # lower-cased
    monkeypatch.setenv("CUTAGENT_OBJECTSTORE_MAX_ATTEMPTS", "9")
    monkeypatch.setenv("CUTAGENT_WORKFLOW_RUNTIME", "TEMPORAL")  # lower-cased
    monkeypatch.setenv("CUTAGENT_REGISTRATION_OPEN", "false")
    monkeypatch.setenv("CUTAGENT_FFMPEG_BIN", "/opt/ffmpeg")
    monkeypatch.setenv("CUTAGENT_DISABLE_BACKGROUND_DISPATCHER", "1")

    settings = build_settings()

    assert settings.storage.backend == "memory"
    assert settings.storage.database_url == "postgresql+psycopg://x/db"
    assert settings.object_store.tiered is False
    assert settings.object_store.backend == "s3"
    assert settings.object_store.s3.max_attempts == 9
    assert settings.workflow.runtime == "temporal"
    assert settings.auth.registration_open is False
    assert settings.media.ffmpeg_bin == "/opt/ffmpeg"
    assert settings.api.disable_background_dispatcher is True


def test_provider_publishing_settings_read_env_overrides(
    clean_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CUTAGENT_PROVIDER_MAX_INFLIGHT", "7")
    monkeypatch.setenv("CUTAGENT_PROVIDER_MAX_QPS", "9")
    monkeypatch.setenv("CUTAGENT_PROVIDER_CIRCUIT_BREAKER", "1")
    monkeypatch.setenv("CUTAGENT_PROVIDER_CIRCUIT_ERROR_RATE", "0.7")
    monkeypatch.setenv("CUTAGENT_PROVIDER_CIRCUIT_WINDOW", "6")
    monkeypatch.setenv("CUTAGENT_ALLOWED_API_HOSTS", "proxy.internal")
    monkeypatch.setenv("CUTAGENT_ENFORCE_PROVIDER_HOST_ALLOWLIST", "1")
    monkeypatch.setenv("CUTAGENT_XIAOVMAO_CDP_HOST", "10.0.0.5")
    monkeypatch.setenv("CUTAGENT_XIAOVMAO_CDP_PORT", "9333")

    prov = build_settings().providers
    assert prov.max_inflight == 7
    assert prov.max_qps == 9
    assert prov.circuit_breaker_enabled is True
    assert prov.circuit_error_rate_threshold == 0.7
    assert prov.circuit_window_hours == 6
    assert prov.allowed_api_hosts == "proxy.internal"
    assert prov.enforce_host_allowlist is True

    pub = build_settings().publishing
    assert pub.xiaovmao_cdp_host == "10.0.0.5"
    assert pub.xiaovmao_cdp_port == 9333


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("8", 8), ("0", 4), ("-3", 4), ("abc", 4), ("", 4)],
)
def test_provider_max_inflight_defensive_parse(
    clean_env, monkeypatch: pytest.MonkeyPatch, raw: str, expected: int
) -> None:
    # Mirror the previous provider_limiter._max_inflight: unset / non-integer /
    # non-positive falls back to the default rather than disabling backpressure.
    monkeypatch.setenv("CUTAGENT_PROVIDER_MAX_INFLIGHT", raw)
    assert build_settings().providers.max_inflight == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0.7", 0.7), ("2", 1.0), ("-1", 0.0), ("abc", 0.5), ("", 0.5)],
)
def test_circuit_error_rate_clamped_to_unit_interval(
    clean_env, monkeypatch: pytest.MonkeyPatch, raw: str, expected: float
) -> None:
    # Mirror the previous circuit_breaker._float_env: invalid/unset -> default,
    # valid -> clamped to [0, 1].
    monkeypatch.setenv("CUTAGENT_PROVIDER_CIRCUIT_ERROR_RATE", raw)
    assert build_settings().providers.circuit_error_rate_threshold == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("5", 5), ("0", 1), ("-9", 1), ("abc", 24), ("", 24)],
)
def test_circuit_window_floored_at_one(
    clean_env, monkeypatch: pytest.MonkeyPatch, raw: str, expected: int
) -> None:
    # Mirror the previous circuit_breaker._int_env: invalid/unset -> default,
    # valid -> floored at 1.
    monkeypatch.setenv("CUTAGENT_PROVIDER_CIRCUIT_WINDOW", raw)
    assert build_settings().providers.circuit_window_hours == expected


def test_circuit_breaker_enabled_only_on_exact_one(
    clean_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mirror the previous strict "== '1'" check (truthy strings do not enable it).
    monkeypatch.setenv("CUTAGENT_PROVIDER_CIRCUIT_BREAKER", "true")
    assert build_settings().providers.circuit_breaker_enabled is False
    monkeypatch.setenv("CUTAGENT_PROVIDER_CIRCUIT_BREAKER", "1")
    assert build_settings().providers.circuit_breaker_enabled is True


def test_build_settings_reads_env_at_call_time(clean_env, monkeypatch: pytest.MonkeyPatch) -> None:
    # The call-time-read contract: a snapshot reflects env at the moment it is
    # built, and a later env change is only visible to a fresh build.
    first = build_settings()
    assert first.object_store.bucket == "cutagent-local"

    monkeypatch.setenv("CUTAGENT_OBJECTSTORE_BUCKET", "cutagent-prod")
    assert first.object_store.bucket == "cutagent-local"  # old snapshot unchanged
    assert build_settings().object_store.bucket == "cutagent-prod"


def test_settings_is_immutable(clean_env) -> None:
    settings = build_settings()
    with pytest.raises(Exception):
        settings.storage.backend = "memory"  # type: ignore[misc]


def test_local_ephemeral_store_honors_configured_bucket(clean_env, tmp_path) -> None:
    # Intentional behavior of the Settings consolidation: the LOCAL ephemeral object
    # store honors a configured bucket (routed through Settings; previously hard-coded
    # for the local backend), while the default stays byte-identical. Locked here so
    # the non-default case is covered rather than being a silent, untested drift.
    from packages.core.config import EphemeralObjectStoreSettings
    from packages.core.storage.object_store_env import _ephemeral_store

    assert EphemeralObjectStoreSettings().bucket == "cutagent-ephemeral"

    cfg = EphemeralObjectStoreSettings(
        backend="local", local_path=str(tmp_path), bucket="custom-ephemeral"
    )
    store = _ephemeral_store(cfg, workflow_runtime="local", client_factory=None)
    assert store.bucket == "custom-ephemeral"
