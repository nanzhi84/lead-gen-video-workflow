#!/usr/bin/env python3
"""Sync media-library MATERIALS metadata from the PROD DB into a LOCAL dev DB,
WITHOUT annotations. Lets a local env index materials uploaded on prod (bytes are
already shared via the cutagent-materials bucket); the local operator annotates
independently.

Copies, for every prod media_asset missing locally:
  - its source artifact row  (case_id NULL'd to decouple from prod cases)
  - the media_asset row       (annotation_status forced to 'pending', case_id NULL)
SKIPS: annotations, material.annotation artifacts, selection ledger/reservations.
Idempotent (ON CONFLICT (id) DO NOTHING). Dry-run by default; --apply to write.

  python scripts/sync_materials.py --prod-dsn postgresql://cutagent:cutagent@<prod>:55432/cutagent --apply
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg
from psycopg.rows import dict_row


def log(m: str) -> None:
    print(m, flush=True)


def norm(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


def columns(cur, table: str) -> list[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,),
    )
    return [r[0] if not isinstance(r, dict) else r["column_name"] for r in cur.fetchall()]


def insert_row(cur, table: str, cols: list[str], row: dict, overrides: dict) -> None:
    vals = []
    for c in cols:
        vals.append(overrides[c] if c in overrides else row.get(c))
    placeholders = ", ".join(["%s"] * len(cols))
    collist = ", ".join(f'"{c}"' for c in cols)
    cur.execute(
        f'INSERT INTO "{table}" ({collist}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING',
        vals,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod-dsn", required=True, help="read-only source (prod) DB")
    ap.add_argument("--local-dsn", default=os.environ.get(
        "CUTAGENT_DATABASE_URL", "postgresql://cutagent:cutagent@127.0.0.1:55432/cutagent"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    prod = psycopg.connect(norm(args.prod_dsn), row_factory=dict_row)
    local = psycopg.connect(norm(args.local_dsn), row_factory=dict_row)
    pc, lc = prod.cursor(), local.cursor()

    lc.execute("SELECT id FROM media_assets")
    local_ids = {r["id"] for r in lc.fetchall()}
    pc.execute("SELECT id, source_artifact_id FROM media_assets")
    prod_assets = pc.fetchall()
    new = [a for a in prod_assets if a["id"] not in local_ids]
    log(f"prod media_assets={len(prod_assets)} local={len(local_ids)} new-to-sync={len(new)}")
    if not new:
        log("nothing to sync."); return 0

    ma_cols = columns(lc, "media_assets")
    art_cols = columns(lc, "artifacts")
    synced_assets = synced_arts = 0
    for a in new:
        # 1) source artifact (must exist before the asset FK)
        sa_id = a["source_artifact_id"]
        if sa_id:
            pc.execute("SELECT * FROM artifacts WHERE id=%s", (sa_id,))
            art = pc.fetchone()
            if art:
                if args.apply:
                    insert_row(lc, "artifacts", art_cols, art, {"case_id": None})
                synced_arts += 1
        # 2) the media_asset row (decoupled + unannotated)
        pc.execute("SELECT * FROM media_assets WHERE id=%s", (a["id"],))
        ma = pc.fetchone()
        if args.apply:
            insert_row(lc, "media_assets", ma_cols, ma,
                       {"case_id": None, "annotation_status": "pending"})
        synced_assets += 1

    if args.apply:
        local.commit()
    log(f"sync: assets={synced_assets} source_artifacts={synced_arts} "
        f"({'applied' if args.apply else 'dry-run'})")
    prod.close(); local.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
