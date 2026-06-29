"""Report (and optionally sweep) the S3 object-store local cache (issue #76).

The boto3 download cache on the Mac mini grows without bound and can fill the
disk, starving the Temporal worker / render temp files / DB backups. This script
reports current usage and, with --sweep, evicts by TTL then total size using the
configured CUTAGENT_OBJECTSTORE_CACHE_TTL_HOURS / _CACHE_MAX_BYTES (overridable
via flags).

    python scripts/cache_status.py
    python scripts/cache_status.py --sweep
    python scripts/cache_status.py --sweep --max-bytes 5000000000 --ttl-hours 168 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.core.config import build_settings  # noqa: E402
from packages.core.storage.object_store import (  # noqa: E402
    object_cache_status,
    sweep_object_cache,
)

# Matches S3ObjectStore's default cache_root.
_DEFAULT_CACHE_ROOT = ".data/objectstore-cache"


def _human(n: int) -> str:
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TiB"


def main() -> int:
    settings = build_settings()
    parser = argparse.ArgumentParser(description="Cutagent object-store cache status / sweep.")
    parser.add_argument("--cache-root", default=_DEFAULT_CACHE_ROOT)
    parser.add_argument("--sweep", action="store_true", help="Evict by TTL then size.")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=settings.object_store.cache_max_bytes,
        help="Size budget for --sweep (0 = unbounded).",
    )
    parser.add_argument(
        "--ttl-hours",
        type=float,
        default=settings.object_store.cache_ttl_hours,
        help="TTL for --sweep (0 = no TTL).",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cache_root = Path(args.cache_root)
    if args.sweep:
        result = sweep_object_cache(
            cache_root, max_bytes=args.max_bytes, ttl_hours=args.ttl_hours
        )
    else:
        result = object_cache_status(cache_root)

    payload = {
        "cache_root": str(cache_root),
        "swept": args.sweep,
        "max_bytes": args.max_bytes,
        "ttl_hours": args.ttl_hours,
        "examined_files": result.examined_files,
        "total_bytes": result.total_bytes,
        "deleted_files": result.deleted_files,
        "freed_bytes": result.freed_bytes,
        "remaining_bytes": result.remaining_bytes,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"cache_root: {cache_root}")
        print(f"  files: {result.examined_files}  total: {_human(result.total_bytes)}")
        if args.sweep:
            print(
                f"  swept: deleted {result.deleted_files} files, "
                f"freed {_human(result.freed_bytes)}, remaining {_human(result.remaining_bytes)}"
            )
        else:
            print("  (use --sweep to evict by TTL then size)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
