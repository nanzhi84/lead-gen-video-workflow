#!/usr/bin/env python3
"""Migrate cutagent objects out of the legacy shared bucket into clean,
purpose-separated buckets, and rewrite all DB URI references.

  materials (media_asset sources + their thumbnails)  -> --materials-bucket (shared)
  everything else cutagent references (outputs)        -> --output-bucket (per env)

Source objects are server-side copied (no download); the legacy bucket is left
intact (cleanup is a separate, later step). Idempotent: existing dest objects and
already-rewritten rows are skipped. Dry-run by default; pass --apply to execute.

Run locally:  CUTAGENT_OBJECTSTORE_* sourced from .env.local
  python scripts/migrate_buckets.py --apply
Run on prod (mac mini), copies any prod-only extras + rewrites the prod DB:
  python scripts/migrate_buckets.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import boto3
import psycopg
from botocore.config import Config

# Columns that may contain s3://<bucket>/<key> references (from a DB-wide scan).
# (table, column, is_jsonb)
REF_COLUMNS = [
    ("artifacts", "uri", False),
    ("artifacts", "oss_uri", False),
    ("artifacts", "payload", True),
    ("media_assets", "thumbnail_uri", False),
    ("finished_videos", "video_artifact", True),
    ("finished_videos", "cover_artifact", True),
    ("finished_videos", "subtitle_artifact", True),
    ("publish_packages", "video_artifact", True),
    ("publish_packages", "cover_artifact", True),
    ("usage_meter_records", "raw_usage", True),
    ("idempotency_records", "response_body", True),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def oss_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["CUTAGENT_OBJECTSTORE_ENDPOINT"],
        aws_access_key_id=os.environ["CUTAGENT_OBJECTSTORE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["CUTAGENT_OBJECTSTORE_SECRET_KEY"],
        region_name=os.environ.get("CUTAGENT_OBJECTSTORE_REGION", "oss-cn-shanghai"),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": os.environ.get("CUTAGENT_OBJECTSTORE_ADDRESSING_STYLE", "virtual")},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def normalize_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


def pk_columns(cur, table: str) -> list[str]:
    cur.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary
        ORDER BY a.attnum
        """,
        (table,),
    )
    cols = [r[0] for r in cur.fetchall()]
    if not cols:
        raise RuntimeError(f"{table}: no primary key found")
    return cols


def build_material_keys(cur, src_bucket: str) -> set[str]:
    """Keys that are media-library MATERIALS: media_asset source artifacts + their
    thumbnails. Everything else cutagent references is an OUTPUT."""
    prefix = f"s3://{src_bucket}/"
    keys: set[str] = set()
    cur.execute(
        """
        SELECT a.uri, a.oss_uri FROM artifacts a
        WHERE a.id IN (SELECT source_artifact_id FROM media_assets WHERE source_artifact_id IS NOT NULL)
        """
    )
    for uri, oss_uri in cur.fetchall():
        for v in (uri, oss_uri):
            if v and v.startswith(prefix):
                keys.add(v[len(prefix):])
    cur.execute("SELECT thumbnail_uri FROM media_assets WHERE thumbnail_uri LIKE %s", (prefix + "%",))
    for (tu,) in cur.fetchall():
        if tu and tu.startswith(prefix):
            keys.add(tu[len(prefix):])
    return keys


def collect_all_keys(cur, src_bucket: str) -> set[str]:
    """Every key referenced anywhere in the DB (across all REF_COLUMNS)."""
    pat = re.compile(re.escape(f"s3://{src_bucket}/") + r'([^"\\]+)')
    keys: set[str] = set()
    for table, col, _is_jsonb in REF_COLUMNS:
        try:
            cur.execute(f'SELECT "{col}"::text FROM "{table}" WHERE "{col}"::text LIKE %s',
                        (f"%{src_bucket}%",))
        except psycopg.Error:
            cur.connection.rollback()
            continue
        for (val,) in cur.fetchall():
            if val:
                keys.update(m.group(1) for m in pat.finditer(val))
    return keys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get("CUTAGENT_DATABASE_URL",
                    "postgresql://cutagent:cutagent@127.0.0.1:55432/cutagent"))
    ap.add_argument("--source-bucket", default="videoretalk-test-bucket")
    ap.add_argument("--materials-bucket", default="cutagent-materials")
    ap.add_argument("--output-bucket", default="cutagent-prod")
    ap.add_argument("--dev-bucket", default="cutagent-dev")
    ap.add_argument("--create-buckets", action="store_true",
                    help="create materials/output/dev buckets if missing")
    ap.add_argument("--no-copy", action="store_true")
    ap.add_argument("--no-rewrite", action="store_true")
    ap.add_argument("--apply", action="store_true", help="execute (default: dry-run)")
    args = ap.parse_args()

    dsn = normalize_dsn(args.dsn)
    src, mat, out = args.source_bucket, args.materials_bucket, args.output_bucket
    cli = oss_client()
    mode = "APPLY" if args.apply else "DRY-RUN"
    log(f"[{mode}] dsn={dsn.split('@')[-1]}  source={src}  materials={mat}  output={out}")

    if args.create_buckets:
        for b in (mat, out, args.dev_bucket):
            try:
                cli.head_bucket(Bucket=b); log(f"  bucket exists: {b}")
            except Exception:
                if args.apply:
                    cli.create_bucket(Bucket=b); log(f"  bucket CREATED: {b}")
                else:
                    log(f"  would create bucket: {b}")

    conn = psycopg.connect(dsn)
    cur = conn.cursor()
    material_keys = build_material_keys(cur, src)
    all_keys = collect_all_keys(cur, src)
    log(f"referenced keys: {len(all_keys)} total  ({len(material_keys & all_keys)} material, "
        f"{len(all_keys - material_keys)} output)")

    def target(key: str) -> str:
        return mat if key in material_keys else out

    # ---- copy ----
    if not args.no_copy:
        copied = skipped = missing = failed = 0
        for key in sorted(all_keys):
            dst = target(key)
            try:
                cli.head_object(Bucket=dst, Key=key); skipped += 1; continue
            except Exception:
                pass
            try:
                cli.head_object(Bucket=src, Key=key)
            except Exception:
                missing += 1
                log(f"  MISSING in source, cannot copy: {src}/{key}")
                continue
            if args.apply:
                try:
                    cli.copy_object(CopySource={"Bucket": src, "Key": key}, Bucket=dst, Key=key)
                    copied += 1
                except Exception as e:
                    failed += 1
                    log(f"  COPY FAILED {src}/{key} -> {dst}: {type(e).__name__}: {str(e)[:120]}")
            else:
                copied += 1
        log(f"copy: copied={copied} skipped(exists)={skipped} missing={missing} failed={failed}")
        if failed:
            log("ABORT: copy failures; not rewriting DB."); return 1

    # ---- rewrite DB ----
    if not args.no_rewrite:
        keys_by_len = sorted(all_keys, key=len, reverse=True)
        total_rows = 0
        for table, col, is_jsonb in REF_COLUMNS:
            pks = pk_columns(cur, table)
            pk_sel = ", ".join(f'"{c}"' for c in pks)
            cur.execute(
                f'SELECT {pk_sel}, "{col}"::text FROM "{table}" WHERE "{col}"::text LIKE %s',
                (f"%{src}%",),
            )
            rows = cur.fetchall()
            changed = 0
            for row in rows:
                pkvals = row[: len(pks)]
                val = row[len(pks)]
                if not val:
                    continue
                new = val
                for key in keys_by_len:
                    if key in val:
                        new = new.replace(f"s3://{src}/{key}", f"s3://{target(key)}/{key}")
                if new != val:
                    if args.apply:
                        where = " AND ".join(f'"{c}" = %s' for c in pks)
                        cast = "::jsonb" if is_jsonb else ""
                        cur.execute(
                            f'UPDATE "{table}" SET "{col}" = %s{cast} WHERE {where}',
                            (new, *pkvals),
                        )
                    changed += 1
            if changed:
                log(f"  rewrite {table}.{col}: {changed} rows")
                total_rows += changed
        if args.apply:
            conn.commit()
        log(f"rewrite: {total_rows} rows {'updated' if args.apply else 'would change'}")
        if args.apply:
            residual = 0
            for table, col, _ in REF_COLUMNS:
                cur.execute(f'SELECT count(*) FROM "{table}" WHERE "{col}"::text LIKE %s',
                            (f"%{src}%",))
                residual += cur.fetchone()[0]
            log(f"residual rows still referencing {src}: {residual}")
    conn.close()
    log(f"[{mode}] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
