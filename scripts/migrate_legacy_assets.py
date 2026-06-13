from __future__ import annotations

import argparse
import os
from pathlib import Path

from packages.migrations.legacy_asset_clients import ImportApiClient, LegacyOssClient
from packages.migrations.legacy_asset_utils import DEFAULT_BUCKET, DEFAULT_UPLOAD_PREFIX, parse_kinds
from packages.migrations.legacy_assets import LegacyAssetMigrator, MigrationResult, run_migration

__all__ = [
    "ImportApiClient",
    "LegacyAssetMigrator",
    "LegacyOssClient",
    "MigrationResult",
    "run_migration",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate legacy OSS asset indexes into genesis imports.")
    parser.add_argument("--case-meta-dir", type=Path, required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:8021")
    parser.add_argument("--cookie", default=os.getenv("CUTAGENT_IMPORT_COOKIE"))
    parser.add_argument("--email", default=os.getenv("CUTAGENT_IMPORT_EMAIL"))
    parser.add_argument("--password", default=os.getenv("CUTAGENT_IMPORT_PASSWORD"))
    parser.add_argument("--dry-run", action="store_true", help="Print the plan only. This is the default.")
    parser.add_argument("--apply", action="store_true", help="Call POST /api/import/batches.")
    parser.add_argument("--kinds", nargs="+", help="Filter: case script bgm broll portrait font cover")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bucket = (
        os.getenv("CUTAGENT_LEGACY_OBJECTSTORE_BUCKET")
        or os.getenv("CUTAGENT_OBJECTSTORE_BUCKET")
        or DEFAULT_BUCKET
    )
    prefix = os.getenv("CUTAGENT_LEGACY_UPLOAD_PREFIX", DEFAULT_UPLOAD_PREFIX)
    import_client = (
        ImportApiClient(args.api_base, cookie=args.cookie, email=args.email, password=args.password)
        if args.apply
        else None
    )
    result = run_migration(
        case_meta_dir=args.case_meta_dir,
        oss_client=LegacyOssClient.from_env(bucket=bucket),
        import_client=import_client,
        apply=bool(args.apply),
        kinds=parse_kinds(args.kinds),
        bucket=bucket,
        upload_prefix=prefix,
    )
    return 1 if result.failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
