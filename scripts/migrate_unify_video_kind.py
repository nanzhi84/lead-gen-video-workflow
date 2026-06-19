#!/usr/bin/env python3
"""Reclassify legacy portrait / b-roll media assets as unified video assets.

This migration is intentionally metadata-only: existing canonical annotations are
reused as-is, with ``meta.material_type`` rewritten to ``video`` when applying.
No VLM analysis is rerun here. Dry-run is the default; ``--apply`` performs one
database commit after all planned row updates are staged.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.core.contracts import AnnotationV4, ClipV4
from packages.planning.material import clip_is_lip_sync_usable

_RECLASSIFY_KINDS = {"portrait", "broll"}


@dataclass
class UnifyPlan:
    reclassify: list[str]
    rerun_candidates: list[tuple[str, str]]


def _validated_annotation(annotation: AnnotationV4) -> AnnotationV4 | None:
    try:
        return AnnotationV4.model_validate(annotation)
    except ValidationError:
        return None


def _has_lip_sync_usable_clip(clips: list[ClipV4]) -> bool:
    for clip in clips:
        try:
            if clip_is_lip_sync_usable(clip):
                return True
        except (AttributeError, TypeError, ValueError):
            continue
    return False


def plan_unify(
    assets: list[tuple[str, str]], annotations: dict[str, AnnotationV4 | None]
) -> UnifyPlan:
    reclassify: list[str] = []
    rerun_candidates: list[tuple[str, str]] = []

    for asset_id, raw_kind in assets:
        kind = str(raw_kind).strip().lower()
        if kind == "video" or kind not in _RECLASSIFY_KINDS:
            continue

        reclassify.append(asset_id)
        if kind != "portrait":
            continue

        annotation = annotations.get(asset_id)
        if annotation is None:
            rerun_candidates.append((asset_id, "no annotation"))
            continue

        parsed = _validated_annotation(annotation)
        if parsed is None or not _has_lip_sync_usable_clip(parsed.clips):
            rerun_candidates.append((asset_id, "no lip-sync-usable clip"))

    return UnifyPlan(reclassify=reclassify, rerun_candidates=rerun_candidates)


def _canonical_by_asset_id(annotation_rows: list[Any]) -> dict[str, Any]:
    annotations: dict[str, Any] = {}
    for row in annotation_rows:
        annotations.setdefault(row.asset_id, row.canonical)
    return annotations


def _updated_canonical(canonical: dict[str, Any]) -> dict[str, Any]:
    meta = canonical.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}
    return {**canonical, "meta": {**meta, "material_type": "video"}}


def run(*, apply: bool, out=sys.stdout) -> int:
    from sqlalchemy.orm.attributes import flag_modified

    from packages.core.storage.database import AnnotationRow, MediaAssetRow
    from packages.core.storage.database import create_database_engine, create_session_factory

    mode = "APPLY" if apply else "DRY-RUN"

    with create_session_factory(create_database_engine())() as session:
        rows = session.query(MediaAssetRow).filter(MediaAssetRow.kind.in_(_RECLASSIFY_KINDS)).all()
        asset_ids = [row.id for row in rows]
        annotation_rows = []
        if asset_ids:
            annotation_rows = (
                session.query(AnnotationRow).filter(AnnotationRow.asset_id.in_(asset_ids)).all()
            )

        annotations = _canonical_by_asset_id(annotation_rows)
        plan = plan_unify([(row.id, row.kind) for row in rows], annotations)
        reclassify_ids = set(plan.reclassify)

        portrait_count = sum(
            1 for row in rows if row.kind == "portrait" and row.id in reclassify_ids
        )
        broll_count = sum(1 for row in rows if row.kind == "broll" and row.id in reclassify_ids)

        if apply:
            for row in rows:
                if row.id in reclassify_ids:
                    row.kind = "video"
            for row in annotation_rows:
                if row.asset_id not in reclassify_ids or not isinstance(row.canonical, dict):
                    continue
                row.canonical = _updated_canonical(row.canonical)
                flag_modified(row, "canonical")
            session.commit()

    print(f"{mode} unify video kind", file=out)
    print(f"portrait->video count: {portrait_count}", file=out)
    print(f"broll->video count: {broll_count}", file=out)
    print(f"rerun candidates: {len(plan.rerun_candidates)}", file=out)
    for asset_id, reason in plan.rerun_candidates:
        print(f"  - {asset_id}: {reason}", file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run", dest="apply", action="store_false", help="Plan only; no DB writes."
    )
    group.add_argument("--apply", dest="apply", action="store_true", help="Commit changes.")
    parser.set_defaults(apply=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(apply=bool(args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
