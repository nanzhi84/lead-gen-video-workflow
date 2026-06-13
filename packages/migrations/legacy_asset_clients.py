from __future__ import annotations

import json
import os
from typing import Any

from packages.migrations.legacy_asset_utils import DEFAULT_BUCKET, is_not_found_error


class LegacyOssClient:
    def __init__(self, client: Any, *, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_env(cls, *, bucket: str | None = None) -> "LegacyOssClient":
        from botocore.config import Config
        import boto3

        resolved_bucket = (
            bucket
            or os.getenv("CUTAGENT_LEGACY_OBJECTSTORE_BUCKET")
            or os.getenv("CUTAGENT_OBJECTSTORE_BUCKET")
            or DEFAULT_BUCKET
        )
        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": os.getenv("CUTAGENT_OBJECTSTORE_ADDRESSING_STYLE", "path")},
            connect_timeout=int(os.getenv("CUTAGENT_OBJECTSTORE_CONNECT_TIMEOUT", "10")),
            read_timeout=int(os.getenv("CUTAGENT_OBJECTSTORE_READ_TIMEOUT", "120")),
            retries={"max_attempts": int(os.getenv("CUTAGENT_OBJECTSTORE_MAX_ATTEMPTS", "5"))},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
        client = boto3.client(
            "s3",
            endpoint_url=os.getenv("CUTAGENT_LEGACY_OBJECTSTORE_ENDPOINT")
            or os.getenv("CUTAGENT_OBJECTSTORE_ENDPOINT"),
            aws_access_key_id=os.getenv("CUTAGENT_LEGACY_OBJECTSTORE_ACCESS_KEY")
            or os.getenv("CUTAGENT_OBJECTSTORE_ACCESS_KEY", ""),
            aws_secret_access_key=os.getenv("CUTAGENT_LEGACY_OBJECTSTORE_SECRET_KEY")
            or os.getenv("CUTAGENT_OBJECTSTORE_SECRET_KEY", ""),
            region_name=os.getenv("CUTAGENT_OBJECTSTORE_REGION", "us-east-1"),
            config=config,
        )
        return cls(client, bucket=resolved_bucket)

    def get_json(self, key: str) -> Any:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if is_not_found_error(exc):
                raise FileNotFoundError(key) from exc
            raise
        return json.loads(response["Body"].read().decode("utf-8"))

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(str(item["Key"]) for item in page.get("Contents", []))
        return keys

    def object_exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if is_not_found_error(exc):
                return False
            raise
        return True


class ImportApiClient:
    def __init__(
        self,
        api_base: str,
        *,
        cookie: str | None = None,
        email: str | None = None,
        password: str | None = None,
    ) -> None:
        import httpx

        headers = {"Cookie": cookie} if cookie and "=" in cookie else None
        cookies = {"cutagent_session": cookie} if cookie and "=" not in cookie else None
        self.client = httpx.Client(base_url=api_base.rstrip("/"), headers=headers, cookies=cookies)
        if email or password:
            if not email or not password:
                raise ValueError("Both email and password are required for login.")
            response = self.client.post("/api/auth/login", json={"email": email, "password": password})
            response.raise_for_status()

    def import_batch(
        self,
        import_type: str,
        rows: list[dict],
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        response = self.client.post(
            "/api/import/batches",
            json={"import_type": import_type, "rows": rows, "idempotency_key": idempotency_key},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
