"""ObjectStore is built lazily, not at import time (issue #64)."""

from __future__ import annotations

import pytest

from packages.core.config import build_settings
from packages.core.storage import object_store as object_store_module
from packages.core.storage import object_store_from_settings


@pytest.fixture(autouse=True)
def _restore_object_store_slot():
    # The process slot is a global; snapshot and restore it so these tests never
    # leak a sentinel/None into other tests that call get_object_store().
    saved = object_store_module._OBJECT_STORE
    try:
        yield
    finally:
        object_store_module._OBJECT_STORE = saved


def test_module_has_no_import_time_construction():
    # After a reset (the import-time state), nothing is built until first access.
    object_store_module.reset_object_store()
    assert object_store_module._OBJECT_STORE is None


def test_get_object_store_builds_lazily_and_caches():
    object_store_module.reset_object_store()
    first = object_store_module.get_object_store()
    assert first is not None
    assert object_store_module.get_object_store() is first  # cached, built once


def test_configure_and_reset_object_store():
    sentinel = object()
    object_store_module.configure_object_store(sentinel)
    assert object_store_module.get_object_store() is sentinel
    object_store_module.reset_object_store()
    rebuilt = object_store_module.get_object_store()
    assert rebuilt is not sentinel and rebuilt is not None


def test_object_store_from_settings_builds_local_store():
    settings = build_settings()  # conftest -> local backend
    store = object_store_from_settings(
        settings.object_store, workflow_runtime="local"
    )
    assert store is not None


def test_temporal_ephemeral_failfast_is_lazy_not_at_import(monkeypatch):
    # The Temporal + node-local-ephemeral fail-fast must fire when the store is
    # BUILT (call time), not merely when the module is imported. The module is
    # already imported (at collection) without raising — proof the construction
    # is no longer at import time.
    monkeypatch.setenv("CUTAGENT_WORKFLOW_RUNTIME", "temporal")
    monkeypatch.setenv("CUTAGENT_OBJECTSTORE_TIERED", "1")
    monkeypatch.setenv("CUTAGENT_EPHEMERAL_OBJECTSTORE_BACKEND", "local")
    from packages.core.storage.object_store import object_store_from_env

    object_store_module.reset_object_store()
    with pytest.raises(RuntimeError):
        object_store_from_env()
