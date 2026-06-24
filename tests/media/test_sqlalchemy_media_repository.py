from __future__ import annotations

from types import SimpleNamespace

from packages.core.storage.database import ArtifactRow
from packages.media.sqlalchemy_repository import SqlAlchemyMediaRepository


class _SignedUrl:
    def __init__(self, url: str) -> None:
        self.url = url


class _ObjectStore:
    def __init__(self) -> None:
        self.signed: list[str] = []

    def signed_url(self, uri: str) -> _SignedUrl:
        self.signed.append(uri)
        return _SignedUrl(f"https://cdn.example/{uri.removeprefix('s3://')}")


class _Session:
    def __init__(self, artifact=None) -> None:
        self.artifact = artifact
        self.get_calls: list[tuple[object, str]] = []

    def get(self, model, row_id: str):
        self.get_calls.append((model, row_id))
        if model is ArtifactRow and row_id == getattr(self.artifact, "id", None):
            return self.artifact
        return None


def test_image_asset_uses_source_artifact_as_thumbnail_when_no_thumbnail_uri():
    object_store = _ObjectStore()
    repository = SqlAlchemyMediaRepository(lambda: None, object_store)
    artifact = SimpleNamespace(
        id="art_image",
        uri="s3://bucket/image.jpg",
        media_info={"media_type": "image", "codec": "mjpeg", "format": "image2"},
    )
    row = SimpleNamespace(kind="image", thumbnail_uri=None, source_artifact_id="art_image")

    url = repository._thumbnail_url_for_asset(_Session(artifact), row)

    assert url == "https://cdn.example/bucket/image.jpg"
    assert object_store.signed == ["s3://bucket/image.jpg"]


def test_asset_thumbnail_uri_still_wins_over_image_source_artifact():
    object_store = _ObjectStore()
    repository = SqlAlchemyMediaRepository(lambda: None, object_store)
    session = _Session(SimpleNamespace(id="art_image", uri="s3://bucket/image.jpg"))
    row = SimpleNamespace(
        kind="image",
        thumbnail_uri="s3://bucket/thumb.jpg",
        source_artifact_id="art_image",
    )

    url = repository._thumbnail_url_for_asset(session, row)

    assert url == "https://cdn.example/bucket/thumb.jpg"
    assert object_store.signed == ["s3://bucket/thumb.jpg"]
    assert session.get_calls == []


def test_non_image_asset_without_thumbnail_does_not_sign_source_as_thumbnail():
    object_store = _ObjectStore()
    repository = SqlAlchemyMediaRepository(lambda: None, object_store)
    session = _Session(SimpleNamespace(id="art_video", uri="s3://bucket/video.mp4"))
    row = SimpleNamespace(kind="video", thumbnail_uri=None, source_artifact_id="art_video")

    assert repository._thumbnail_url_for_asset(session, row) is None
    assert object_store.signed == []
    assert session.get_calls == []
