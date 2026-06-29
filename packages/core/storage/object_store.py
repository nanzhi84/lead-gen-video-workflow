from __future__ import annotations

import hashlib
import io
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from packages.core.contracts import SignedUrlResponse, utcnow


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Compute the sha256 of a file by streaming it, without buffering it in RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_bucket_absent_error(exc: Exception) -> bool:
    # head_bucket on a missing bucket raises ClientError with a 404 / NoSuchBucket
    # code; anything else (auth, network) must propagate.
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error", {}) if isinstance(response.get("Error"), dict) else {}
        if str(error.get("Code")) in {"404", "NoSuchBucket", "NotFound"}:
            return True
        status = response.get("ResponseMetadata", {})
        if isinstance(status, dict) and status.get("HTTPStatusCode") == 404:
            return True
    return False


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
    def prepare_upload(
        self,
        filename: str,
        purpose: str,
        *,
        content_key: str | None = None,
        tier: str = "durable",
    ) -> ObjectRef:
        raise NotImplementedError

    def put_bytes(self, ref: ObjectRef, content: bytes) -> StoredObject:
        raise NotImplementedError

    def get_bytes(self, ref: ObjectRef) -> bytes:
        raise NotImplementedError

    def upload_file(self, local_path: Path, ref: ObjectRef) -> StoredObject:
        """Store a file by path. Default falls back to a full read; streaming
        backends (S3) override this to avoid buffering whole objects in RAM."""
        return self.put_bytes(ref, Path(local_path).read_bytes())

    def download_file(self, ref: ObjectRef, local_path: Path) -> Path:
        """Fetch an object to a local path. Default falls back to a full read;
        streaming backends (S3) override this to avoid buffering in RAM."""
        target = Path(local_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.get_bytes(ref))
        return target

    def exists(self, ref: ObjectRef) -> bool:
        raise NotImplementedError

    def signed_url(self, uri: str, *, expires_in: timedelta = timedelta(minutes=15)) -> SignedUrlResponse:
        raise NotImplementedError

    def delete(self, uri: str) -> None:
        raise NotImplementedError


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path, bucket: str = "cutagent-local") -> None:
        self.root = root
        self.bucket = bucket
        self.root.mkdir(parents=True, exist_ok=True)

    def prepare_upload(
        self,
        filename: str,
        purpose: str,
        *,
        content_key: str | None = None,
        tier: str = "durable",
    ) -> ObjectRef:
        safe_name = filename.replace("\\", "_").replace("/", "_")
        key_segment = content_key if content_key is not None else uuid4().hex
        key = f"{purpose}/{key_segment}/{safe_name}"
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

    def get_bytes(self, ref: ObjectRef) -> bytes:
        return self._path(ref).read_bytes()

    def exists(self, ref: ObjectRef) -> bool:
        return self._path(ref).exists()

    def signed_url(self, uri: str, *, expires_in: timedelta = timedelta(minutes=15)) -> SignedUrlResponse:
        return SignedUrlResponse(
            url=uri,
            expires_at=utcnow() + expires_in,
            request_id="req_local",
        )

    def delete(self, uri: str) -> None:
        ref = parse_local_uri(uri)
        path = self._path(ref)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        parent = path.parent
        while parent != self.root and parent.is_relative_to(self.root):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def _path(self, ref: ObjectRef) -> Path:
        if ref.bucket != self.bucket:
            raise ValueError(f"Object bucket {ref.bucket} is not managed by this store.")
        return self.root / ref.key


class S3ObjectStore(ObjectStore):
    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        read_buckets: tuple[str, ...] = (),
        access_key: str,
        secret_key: str,
        region_name: str = "us-east-1",
        addressing_style: str = "path",
        client: Any | None = None,
        client_factory: Callable[..., Any] | None = None,
        cache_root: Path | None = None,
        multipart_threshold_mb: int = 8,
        multipart_chunk_mb: int = 8,
        max_concurrency: int = 4,
        connect_timeout: int = 10,
        read_timeout: int = 120,
        max_attempts: int = 5,
    ) -> None:
        from boto3.s3.transfer import TransferConfig

        self.endpoint_url = endpoint_url
        self.bucket = bucket
        # Buckets this store may READ from: the write bucket plus any read-only
        # source/materials buckets. Writes always target self.bucket only.
        self._read_buckets = frozenset({bucket, *read_buckets})
        self.cache_root = cache_root or Path(".data/objectstore-cache")
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._transfer_config = TransferConfig(
            multipart_threshold=multipart_threshold_mb * 1024 * 1024,
            multipart_chunksize=multipart_chunk_mb * 1024 * 1024,
            max_concurrency=max_concurrency,
            use_threads=True,
        )
        self._client = client or self._build_client(
            client_factory=client_factory,
            endpoint_url=endpoint_url,
            access_key=access_key,
            secret_key=secret_key,
            region_name=region_name,
            addressing_style=addressing_style,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            max_attempts=max_attempts,
        )
        self._ensure_bucket()

    def prepare_upload(
        self,
        filename: str,
        purpose: str,
        *,
        content_key: str | None = None,
        tier: str = "durable",
    ) -> ObjectRef:
        safe_name = filename.replace("\\", "_").replace("/", "_")
        key_segment = content_key if content_key is not None else uuid4().hex
        key = f"{purpose}/{key_segment}/{safe_name}"
        return ObjectRef(bucket=self.bucket, key=key, uri=f"s3://{self.bucket}/{key}")

    def put_bytes(self, ref: ObjectRef, content: bytes) -> StoredObject:
        self._validate_write_ref(ref)
        self._client.upload_fileobj(
            io.BytesIO(content),
            ref.bucket,
            ref.key,
            Config=self._transfer_config,
        )
        path = self._cache_path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return StoredObject(
            ref=ref,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    def get_bytes(self, ref: ObjectRef) -> bytes:
        self._validate_read_ref(ref)
        buf = io.BytesIO()
        self._client.download_fileobj(ref.bucket, ref.key, buf, Config=self._transfer_config)
        return buf.getvalue()

    def upload_file(self, local_path: Path, ref: ObjectRef) -> StoredObject:
        # Streaming, multipart upload by path: boto3's upload_file never reads the
        # whole object into RAM (it streams from disk in multipart chunks).
        self._validate_write_ref(ref)
        source = Path(local_path)
        self._client.upload_file(
            str(source),
            ref.bucket,
            ref.key,
            Config=self._transfer_config,
        )
        cache_path = self._cache_path(ref)
        if source.resolve() != cache_path.resolve():
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, cache_path)
        return StoredObject(
            ref=ref,
            size_bytes=source.stat().st_size,
            sha256=sha256_file(source),
        )

    def download_file(self, ref: ObjectRef, local_path: Path) -> Path:
        # Streaming download by path into the on-disk cache; no full BytesIO buffer.
        self._validate_read_ref(ref)
        target = Path(local_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(
            ref.bucket,
            ref.key,
            str(target),
            Config=self._transfer_config,
        )
        return target

    def exists(self, ref: ObjectRef) -> bool:
        self._validate_read_ref(ref)
        try:
            self._client.head_object(Bucket=ref.bucket, Key=ref.key)
        except Exception as exc:
            if _is_not_found_error(exc):
                return False
            raise
        return True

    def signed_url(self, uri: str, *, expires_in: timedelta = timedelta(minutes=15)) -> SignedUrlResponse:
        ref = parse_object_uri(uri)
        self._validate_read_ref(ref)
        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": ref.bucket, "Key": ref.key},
            ExpiresIn=int(expires_in.total_seconds()),
        )
        return SignedUrlResponse(url=url, expires_at=utcnow() + expires_in, request_id="req_s3")

    def delete(self, uri: str) -> None:
        ref = parse_object_uri(uri)
        self._validate_write_ref(ref)
        self._client.delete_object(Bucket=ref.bucket, Key=ref.key)
        try:
            self._cache_path(ref).unlink()
        except FileNotFoundError:
            pass

    def _path(self, ref: ObjectRef) -> Path:
        self._validate_read_ref(ref)
        path = self._cache_path(ref)
        if not path.exists():
            self.download_file(ref, path)
        return path

    def _cache_path(self, ref: ObjectRef) -> Path:
        return self.cache_root / ref.bucket / ref.key

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except Exception as exc:
            if not _is_bucket_absent_error(exc):
                raise
            self._client.create_bucket(Bucket=self.bucket)

    def _validate_write_ref(self, ref: ObjectRef) -> None:
        if ref.bucket != self.bucket:
            raise ValueError(f"Object bucket {ref.bucket} is not writable by this store.")

    def _validate_read_ref(self, ref: ObjectRef) -> None:
        if ref.bucket not in self._read_buckets:
            raise ValueError(f"Object bucket {ref.bucket} is not readable by this store.")

    @staticmethod
    def _build_client(
        *,
        client_factory: Callable[..., Any] | None,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region_name: str,
        addressing_style: str,
        connect_timeout: int,
        read_timeout: int,
        max_attempts: int,
    ) -> Any:
        from botocore.config import Config

        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": addressing_style},
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"max_attempts": max_attempts, "mode": "standard"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
        if client_factory is None:
            import boto3

            # Force SigV4 presigned URLs (current standard; SigV2 is deprecated).
            return boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region_name,
                config=config,
            )
        return client_factory(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
            config=config,
        )


def parse_local_uri(uri: str) -> ObjectRef:
    for prefix in ("local://", "s3://"):
        if uri.startswith(prefix):
            return _parse_uri_tail(uri, prefix)
    raise ValueError(f"Unsupported local object URI: {uri}")


def parse_object_uri(uri: str) -> ObjectRef:
    for prefix in ("local://", "s3://"):
        if uri.startswith(prefix):
            return _parse_uri_tail(uri, prefix)
    raise ValueError(f"Unsupported object URI: {uri}")


def _parse_uri_tail(uri: str, prefix: str) -> ObjectRef:
    tail = uri[len(prefix) :]
    bucket, _, key = tail.partition("/")
    if not bucket or not key:
        raise ValueError(f"Invalid object URI: {uri}")
    return ObjectRef(bucket=bucket, key=key, uri=uri)


def _is_not_found_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        return str(code) in {"404", "NoSuchBucket", "NoSuchKey", "NotFound"}
    return False


from packages.core.storage.tiered_object_store import TieredObjectStore
from packages.core.storage.object_store_env import (
    object_store_from_env,
    object_store_from_settings,
)


# Built lazily on first get_object_store() rather than at import time (issue #64):
# importing this module must NOT read the environment, open a network connection
# (S3 head_bucket in __init__), or trigger the Temporal ephemeral fail-fast — all
# of which are import-order/timing hazards in tests, scripts, and OpenAPI export.
# The store is constructed once at first use (API lifespan / worker startup /
# first node activity) and cached. Tests still monkeypatch this slot directly or
# patch ``digital_human.get_object_store``; both seams are preserved.
_OBJECT_STORE: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    global _OBJECT_STORE
    if _OBJECT_STORE is None:
        _OBJECT_STORE = object_store_from_env()
    return _OBJECT_STORE


def configure_object_store(store: ObjectStore) -> None:
    """Explicitly install the process object store.

    Lets the API lifespan / worker startup build the store from an already-built
    ``Settings`` (via ``object_store_from_settings``) and inject it, instead of
    relying on the lazy env-read default. Overrides any cached store.
    """
    global _OBJECT_STORE
    _OBJECT_STORE = store


def reset_object_store() -> None:
    """Drop the cached store so the next ``get_object_store()`` rebuilds from the
    current environment. For tests and explicit reconfiguration."""
    global _OBJECT_STORE
    _OBJECT_STORE = None


__all__ = [
    "ObjectRef",
    "ObjectStore",
    "LocalObjectStore",
    "S3ObjectStore",
    "TieredObjectStore",
    "object_store_from_env",
    "object_store_from_settings",
    "get_object_store",
    "configure_object_store",
    "reset_object_store",
    "parse_object_uri",
]
