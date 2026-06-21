#!/usr/bin/env python3
"""Delete media_assets whose source object does NOT exist in object storage
(dangling references — e.g. broll/bgm bytes that were never synced to OSS).
Removes the asset, its annotations (FK cascade) and its now-orphan source
artifact. Dry-run by default; --apply to execute.

  python scripts/clean_dangling_materials.py --apply   # CUTAGENT_OBJECTSTORE_* sourced
"""
from __future__ import annotations

import argparse
import os
import sys

import boto3
import psycopg
from botocore.config import Config


def log(m: str) -> None:
    print(m, flush=True)


def norm(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://")


def oss():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["CUTAGENT_OBJECTSTORE_ENDPOINT"],
        aws_access_key_id=os.environ["CUTAGENT_OBJECTSTORE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["CUTAGENT_OBJECTSTORE_SECRET_KEY"],
        region_name=os.environ.get("CUTAGENT_OBJECTSTORE_REGION", "oss-cn-shanghai"),
        config=Config(signature_version="s3v4",
                      s3={"addressing_style": os.environ.get("CUTAGENT_OBJECTSTORE_ADDRESSING_STYLE", "virtual")},
                      request_checksum_calculation="when_required",
                      response_checksum_validation="when_required"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get(
        "CUTAGENT_DATABASE_URL", "postgresql://cutagent:cutagent@127.0.0.1:55432/cutagent"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cli = oss()
    conn = psycopg.connect(norm(args.dsn))
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.title, m.kind, a.id, a.uri
        FROM media_assets m JOIN artifacts a ON a.id = m.source_artifact_id
        WHERE a.uri LIKE 's3://%'
    """)
    rows = cur.fetchall()
    dangling = []  # (asset_id, artifact_id)
    for asset_id, title, kind, art_id, uri in rows:
        bucket, _, key = uri[len("s3://"):].partition("/")
        try:
            cli.head_object(Bucket=bucket, Key=key)
        except Exception:
            dangling.append((asset_id, art_id))
            log(f"  DANGLING {kind:14} {str(title)[:32]:32} -> {bucket}/{key[:48]}")
    log(f"checked {len(rows)} OSS-backed assets; dangling={len(dangling)}")
    if not dangling:
        log("nothing to clean."); return 0

    asset_ids = [d[0] for d in dangling]
    art_ids = [d[1] for d in dangling]
    if args.apply:
        cur.execute("DELETE FROM annotations WHERE asset_id = ANY(%s)", (asset_ids,))
        ann = cur.rowcount
        cur.execute("DELETE FROM selection_ledger WHERE asset_id = ANY(%s)", (asset_ids,))
        sl = cur.rowcount
        cur.execute("DELETE FROM selection_reservations WHERE asset_id = ANY(%s)", (asset_ids,))
        sr = cur.rowcount
        cur.execute("DELETE FROM media_assets WHERE id = ANY(%s)", (asset_ids,))
        ma = cur.rowcount
        # delete now-orphan source artifacts (not referenced by any remaining asset)
        cur.execute("""DELETE FROM artifacts WHERE id = ANY(%s)
                       AND id NOT IN (SELECT source_artifact_id FROM media_assets
                                      WHERE source_artifact_id IS NOT NULL)""", (art_ids,))
        art = cur.rowcount
        conn.commit()
        log(f"deleted: media_assets={ma} annotations={ann} artifacts={art} "
            f"selection_ledger={sl} selection_reservations={sr}")
    else:
        log(f"DRY-RUN: would delete {len(asset_ids)} assets + their annotations/artifacts")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
