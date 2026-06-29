"""Gated real-OSS verification of the browser-direct upload primitives.

Mirrors the design-time smoke: a presigned PUT (no AWS auth, like the browser) ->
HEAD -> server-side copy (staging->final) -> delete. Object-level only; it does NOT
mutate bucket CORS/lifecycle. Skipped unless CUTAGENT_RUN_OSS_TESTS=1 with a real
s3/OSS backend configured (CUTAGENT_OBJECTSTORE_* access key present).
"""

from __future__ import annotations

import os
import secrets
import urllib.request
from datetime import timedelta

import pytest

if os.getenv("CUTAGENT_RUN_OSS_TESTS") != "1":
    pytest.skip("Set CUTAGENT_RUN_OSS_TESTS=1 to run real-OSS upload tests.", allow_module_level=True)

from packages.core.config import build_object_store_settings
from packages.core.storage.object_store_env import object_store_from_env


def _require_s3():
    cfg = build_object_store_settings()
    if cfg.backend != "s3" or not cfg.s3.access_key:
        pytest.skip("Real-OSS test needs an s3 backend with credentials.")
    return cfg


def test_presigned_put_head_and_copy_against_real_oss():
    cfg = _require_s3()
    store = object_store_from_env()
    token = secrets.token_hex(6)
    staging = store.prepare_upload("probe.bin", "incoming/uploads", content_key=token)

    # Browser-style PUT: raw body to the presigned URL, no AWS auth.
    signed = store.signed_put_url(staging.uri, content_type="application/octet-stream",
                                  expires_in=timedelta(minutes=5))
    body = b"cutagent-oss-direct-probe"
    req = urllib.request.Request(signed.url, data=body, method="PUT",
                                 headers={"Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        assert resp.status in (200, 201)

    head = store.head(staging.uri)
    assert head.size == len(body)

    # Server-side copy staging -> a final key, then drop staging.
    final = store.prepare_upload("probe.bin", "video", content_key=token)
    try:
        store.copy(staging.uri, final.uri)
        assert store.head(final.uri).size == len(body)
    finally:
        store.delete(staging.uri)
        try:
            store.delete(final.uri)
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass

    _ = cfg  # configuration was exercised via object_store_from_env
