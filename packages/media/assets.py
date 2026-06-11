from __future__ import annotations

from pathlib import Path

from packages.core.storage.object_store import ObjectStore, parse_local_uri


def local_object_path(object_store: ObjectStore, uri: str) -> Path:
    ref = parse_local_uri(uri)
    path_method = getattr(object_store, "_path", None)
    if callable(path_method):
        return path_method(ref)
    root = getattr(object_store, "root", None)
    if root is None:
        raise ValueError(f"Object store cannot resolve local paths for URI: {uri}")
    return Path(root) / ref.key


def store_file(object_store: ObjectStore, path: Path, *, purpose: str):
    ref = object_store.prepare_upload(path.name, purpose)
    return object_store.put_bytes(ref, path.read_bytes())
