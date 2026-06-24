from __future__ import annotations

import pytest

from packages.ai.gateway.provider_context import ProviderInvocationContext
from packages.ai.gateway.provider_gateway import ProviderCall, ProviderRuntimeError
from packages.core.contracts import ArtifactKind, ErrorCode, ProviderOptionsSchemaRef, ProviderProfile
from packages.core.storage.object_store import LocalObjectStore, ObjectRef
from packages.core.storage.repository import Repository


class RecordingLocalObjectStore(LocalObjectStore):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.prepare_calls: list[tuple[str, str, str | None, str]] = []

    def prepare_upload(
        self,
        filename: str,
        purpose: str,
        *,
        content_key: str | None = None,
        tier: str = "durable",
    ):
        self.prepare_calls.append((filename, purpose, content_key, tier))
        return super().prepare_upload(filename, purpose, content_key=content_key, tier=tier)


class MissingAfterUploadObjectStore(RecordingLocalObjectStore):
    def exists(self, ref: ObjectRef) -> bool:
        return False


def _context(repository: Repository, object_store: LocalObjectStore) -> ProviderInvocationContext:
    profile = ProviderProfile(
        id="provider.profile",
        provider_id="provider",
        model_id="model",
        capability="tts.speech",
        display_name="Provider",
        environment="local",
        options_schema_ref=ProviderOptionsSchemaRef(schema_id="provider.tts.options"),
    )
    return ProviderInvocationContext(
        repository=repository,
        profile=profile,
        invocation_id="pinv_1",
        secret_store=None,
        object_store=object_store,
    )


def _call(profile_id: str = "provider.profile") -> ProviderCall:
    return ProviderCall(
        case_id="case_demo",
        run_id="run_1",
        node_run_id="nr_1",
        provider_profile_id=profile_id,
        capability_id="tts.speech",
    )


def test_store_media_bytes_forwards_tier_to_object_store(tmp_path, media_fixture_factory):
    repository = Repository()
    object_store = RecordingLocalObjectStore(tmp_path / "objects", bucket="cutagent-ephemeral")
    context = _context(repository, object_store)
    call = _call()
    audio = media_fixture_factory.audio(duration_sec=1.0, filename="provider-tts.wav")

    artifact = context.store_media_bytes(
        content=audio.read_bytes(),
        filename="provider-tts.wav",
        purpose="generated-audio",
        kind=ArtifactKind.audio_tts,
        call=call,
        tier="ephemeral",
    )

    assert object_store.prepare_calls == [
        ("provider-tts.wav", "generated-audio", None, "ephemeral")
    ]
    assert artifact.uri and artifact.uri.startswith("local://cutagent-ephemeral/")
    assert artifact.size_bytes == audio.stat().st_size
    assert artifact.media_info and artifact.media_info.media_type == "audio"


def test_store_media_file_uploads_and_records_size(tmp_path, media_fixture_factory):
    repository = Repository()
    object_store = RecordingLocalObjectStore(tmp_path / "objects", bucket="cutagent-durable")
    context = _context(repository, object_store)
    call = _call()
    video = media_fixture_factory.video(duration_sec=1.0, filename="seedance.mp4")

    artifact = context.store_media_file(
        local_path=video,
        filename="seedance.mp4",
        purpose="generated-video",
        kind=ArtifactKind.video_rendered,
        call=call,
    )

    assert artifact.uri and artifact.uri.startswith("local://cutagent-durable/")
    assert artifact.size_bytes == video.stat().st_size
    assert artifact.media_info and artifact.media_info.media_type == "video"


def test_store_media_bytes_fails_when_object_missing_after_upload(
    tmp_path, media_fixture_factory
):
    repository = Repository()
    object_store = MissingAfterUploadObjectStore(
        tmp_path / "objects",
        bucket="cutagent-durable",
    )
    context = _context(repository, object_store)
    call = _call()
    audio = media_fixture_factory.audio(duration_sec=1.0, filename="provider-tts.wav")

    with pytest.raises(ProviderRuntimeError) as exc_info:
        context.store_media_bytes(
            content=audio.read_bytes(),
            filename="provider-tts.wav",
            purpose="generated-audio",
            kind=ArtifactKind.audio_tts,
            call=call,
        )

    assert exc_info.value.code == ErrorCode.artifact_missing
    assert not repository.artifacts
