from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.core.contracts import PrepareUploadRequest, PrepareUploadResponse
from packages.core.contracts.media import ALLOWED_UPLOAD_CONTENT_TYPES, UploadKind

_100_MIB = 100 * 1024 * 1024


def test_size_cap_enforced():
    PrepareUploadRequest(
        kind=UploadKind.publish_video, filename="v.mp4",
        content_type="video/mp4", size_bytes=_100_MIB,
    )
    with pytest.raises(ValidationError):
        PrepareUploadRequest(
            kind=UploadKind.publish_video, filename="v.mp4",
            content_type="video/mp4", size_bytes=_100_MIB + 1,
        )


def test_multipart_field_removed():
    assert "multipart" not in PrepareUploadRequest.model_fields


def test_allowlist_covers_every_kind():
    assert set(ALLOWED_UPLOAD_CONTENT_TYPES) == set(UploadKind)
    assert "video/mp4" in ALLOWED_UPLOAD_CONTENT_TYPES[UploadKind.publish_video]
    assert "audio/mpeg" in ALLOWED_UPLOAD_CONTENT_TYPES[UploadKind.voice_reference]
    assert "font/ttf" in ALLOWED_UPLOAD_CONTENT_TYPES[UploadKind.font]


def test_prepare_response_shape():
    fields = set(PrepareUploadResponse.model_fields)
    assert {"upload_session", "put_url", "put_content_type", "expires_at"} <= fields
