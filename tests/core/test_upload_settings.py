from __future__ import annotations

from packages.core.config.settings import UploadSettings, build_settings


def test_upload_settings_defaults():
    s = UploadSettings()
    assert s.presign_ttl_seconds == 900
    assert s.cors_allowed_origins == ()


def test_build_settings_upload_defaults(monkeypatch):
    for key in (
        "CUTAGENT_UPLOAD_PRESIGN_TTL_SECONDS",
        "CUTAGENT_UPLOAD_CORS_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)
    upload = build_settings().upload
    assert upload.presign_ttl_seconds == 900
    assert "https://app.shuying.cyou" in upload.cors_allowed_origins
