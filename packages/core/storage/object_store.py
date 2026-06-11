from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from packages.core.contracts import SignedUrlResponse, utcnow


@dataclass(frozen=True)
class ObjectRef:
    bucket: str
    key: str
    uri: str


@dataclass(frozen=True)
class StoredObject:
    ref: ObjectRef
    size_bytes: int
    sha256: str


class ObjectStore:
    def prepare_upload(self, filename: str, purpose: str) -> ObjectRef:
        raise NotImplementedError

    def put_bytes(self, ref: ObjectRef, content: bytes) -> StoredObject:
        raise NotImplementedError

    def signed_url(self, uri: str, *, expires_in: timedelta = timedelta(minutes=15)) -> SignedUrlResponse:
        raise NotImplementedError


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path, bucket: str = "cutagent-local") -> None:
        self.root = root
        self.bucket = bucket
        self.root.mkdir(parents=True, exist_ok=True)

    def prepare_upload(self, filename: str, purpose: str) -> ObjectRef:
        safe_name = filename.replace("\\", "_").replace("/", "_")
        key = f"{purpose}/{uuid4().hex}/{safe_name}"
        return ObjectRef(bucket=self.bucket, key=key, uri=f"local://{self.bucket}/{key}")

    def put_bytes(self, ref: ObjectRef, content: bytes) -> StoredObject:
        path = self._path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return StoredObject(
            ref=ref,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    def signed_url(self, uri: str, *, expires_in: timedelta = timedelta(minutes=15)) -> SignedUrlResponse:
        return SignedUrlResponse(
            url=uri,
            expires_at=utcnow() + expires_in,
            request_id="req_local",
        )

    def _path(self, ref: ObjectRef) -> Path:
        if ref.bucket != self.bucket:
            raise ValueError(f"Object bucket {ref.bucket} is not managed by this store.")
        return self.root / ref.key


def object_store_from_env() -> ObjectStore:
    root = Path(os.getenv("CUTAGENT_LOCAL_OBJECTSTORE_PATH", ".data/objectstore"))
    bucket = os.getenv("CUTAGENT_OBJECTSTORE_BUCKET", "cutagent-local")
    return LocalObjectStore(root=root, bucket=bucket)


_OBJECT_STORE = object_store_from_env()


def get_object_store() -> ObjectStore:
    return _OBJECT_STORE


def parse_local_uri(uri: str) -> ObjectRef:
    prefix = "local://"
    if not uri.startswith(prefix):
        raise ValueError(f"Unsupported local object URI: {uri}")
    tail = uri[len(prefix) :]
    bucket, _, key = tail.partition("/")
    if not bucket or not key:
        raise ValueError(f"Invalid local object URI: {uri}")
    return ObjectRef(bucket=bucket, key=key, uri=uri)

