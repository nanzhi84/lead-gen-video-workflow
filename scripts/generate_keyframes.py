#!/usr/bin/env python3
"""Render evidence-frame keyframes for annotated assets and back-fill the canonical.

Stage-B write utility (IMPLEMENTATION ONLY in this phase — do not run until
Stage B). For every annotated media asset it:

  1. Loads the latest ``annotations.canonical`` row and coerces it to an
     ``AnnotationV4`` to read ``meta.duration`` + ``evidence_frames`` (seconds).
  2. For each evidence-frame timestamp, runs ffmpeg against the asset's *signed*
     OSS video URL (``-ss <t> -i <url> -frames:v 1 frame.jpg``) — no full
     download, ffmpeg seeks over HTTP.
  3. Uploads each frame to the legacy OSS at
     ``digital-human-platform/dev/uploads/keyframes/<asset_id>/<idx>.jpg``.
  4. Writes ``canonical.evidence_frame_images = [{time, image_url}, ...]`` back to
     the annotation row, where ``image_url`` is the object-store uri
     (``s3://<bucket>/<key>``) so the editor signs it on read, exactly like
     ``media_assets.thumbnail_uri``.

Idempotent: a frame whose object already exists in OSS is reused (not
re-rendered/re-uploaded), and ``evidence_frame_images`` is rebuilt from the full
evidence-frame set each run, so re-running is a no-op once every frame exists.

Modes
-----
``--apply``  commit (render + upload + write back). Default is dry-run: it prints
the plan (assets, per-asset frame counts, target keys) and touches nothing.
``--limit N`` cap the number of assets processed (0 = no limit).

Credentials / connections mirror ``backfill_media_fields.py``: DB via
``create_database_engine``; OSS via ``LegacyOssClient`` (boto3) with Aliyun creds
bridged from ``--api-keys`` (default ``<repo>/.data/api_keys.json``).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.migrations.legacy_asset_utils import DEFAULT_BUCKET, DEFAULT_UPLOAD_PREFIX

# Reuse the api_keys → env bridge + key normalization from the backfill script so
# both Stage-A/Stage-B utilities resolve OSS identically.
from scripts.backfill_media_fields import (
    _bridge_oss_env,
    _default_api_keys,
    _load_api_keys,
    _normalize_key,
)

_KEYFRAME_SUBPREFIX = "keyframes"
_SIGN_EXPIRES_SECONDS = 3600


# ── canonical helpers ──────────────────────────────────────────────────────────


def _coerce_annotation_v4(canonical: dict) -> Any | None:
    """Coerce a canonical dict into AnnotationV4, or None if it is not a V4 shape.

    The annotation row can hold either the minimal editor canonical
    (``{labels, kind}``) or a full AnnotationV4 dump; only the latter carries
    ``evidence_frames``.
    """
    from packages.core.contracts.media import AnnotationV4
    from pydantic import ValidationError

    if not isinstance(canonical, dict) or "meta" not in canonical:
        return None
    try:
        return AnnotationV4.model_validate(canonical)
    except ValidationError:
        return None


def _evidence_frames(annotation: Any) -> list[float]:
    return [float(t) for t in getattr(annotation, "evidence_frames", []) or []]


# ── OSS plumbing (raw boto3 via LegacyOssClient.client) ────────────────────────


def _signed_get_url(oss_client: Any, key: str) -> str:
    return oss_client.client.generate_presigned_url(
        "get_object",
        Params={"Bucket": oss_client.bucket, "Key": key},
        ExpiresIn=_SIGN_EXPIRES_SECONDS,
    )


def _object_exists(oss_client: Any, key: str) -> bool:
    return oss_client.object_exists(key)


def _upload_jpg(oss_client: Any, local_path: Path, key: str) -> None:
    oss_client.client.upload_file(
        str(local_path),
        oss_client.bucket,
        key,
        ExtraArgs={"ContentType": "image/jpeg"},
    )


def _keyframe_key(upload_prefix: str, asset_id: str, idx: int) -> str:
    return f"{upload_prefix}{_KEYFRAME_SUBPREFIX}/{asset_id}/{idx}.jpg"


# ── ffmpeg frame extraction ────────────────────────────────────────────────────


def _ffmpeg_bin() -> str:
    from packages.media.video.ffmpeg import ffmpeg_bin

    return ffmpeg_bin()


def _extract_frame(*, video_url: str, time_sec: float, out_path: Path) -> None:
    # -ss before -i seeks (fast, HTTP range); -frames:v 1 grabs a single frame.
    args = [
        _ffmpeg_bin(),
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, time_sec):.3f}",
        "-i",
        video_url,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]
    subprocess.run(args, check=True, capture_output=True, text=True)


# ── driver ─────────────────────────────────────────────────────────────────────


def _artifact_video_key(artifact: Any, upload_prefix: str) -> str | None:
    for candidate in (getattr(artifact, "oss_uri", None), getattr(artifact, "uri", None)):
        key = _normalize_key(candidate, upload_prefix)
        if key:
            return key
    return None


def _video_url_for(artifact: Any, oss_client: Any, upload_prefix: str) -> str | None:
    """Resolve a fetchable video URL for ffmpeg input.

    Prefer signing the OSS object; if the artifact already carries an http(s) uri
    (rare) use it directly.
    """
    key = _artifact_video_key(artifact, upload_prefix)
    if key:
        return _signed_get_url(oss_client, key)
    for candidate in (getattr(artifact, "uri", None), getattr(artifact, "oss_uri", None)):
        if candidate and str(candidate).startswith(("http://", "https://")):
            return str(candidate)
    return None


def run(
    *,
    apply: bool,
    limit: int,
    bucket: str,
    upload_prefix: str,
    oss_client: Any,
    out=sys.stdout,
) -> int:
    from packages.core.storage.database import (
        AnnotationRow,
        ArtifactRow,
        MediaAssetRow,
        create_database_engine,
        create_session_factory,
    )
    from sqlalchemy import select

    mode = "APPLY" if apply else "DRY-RUN"
    assets_with_frames = 0
    frames_planned = 0
    frames_rendered = 0
    frames_reused = 0
    images_written = 0
    skipped: list[str] = []

    session_factory = create_session_factory(create_database_engine())
    with session_factory() as session:
        statement = (
            select(MediaAssetRow)
            .where(MediaAssetRow.annotation_status == "annotated")
            .order_by(MediaAssetRow.updated_at.desc())
        )
        rows = session.scalars(statement).all()
        if limit:
            rows = rows[:limit]

        for asset in rows:
            ann_row = session.scalar(
                select(AnnotationRow)
                .where(AnnotationRow.asset_id == asset.id)
                .order_by(AnnotationRow.updated_at.desc())
                .limit(1)
            )
            if ann_row is None:
                skipped.append(f"{asset.id}: annotated but no annotation row")
                continue
            annotation = _coerce_annotation_v4(ann_row.canonical or {})
            if annotation is None:
                skipped.append(f"{asset.id}: canonical is not an AnnotationV4 (no evidence_frames)")
                continue
            frames = _evidence_frames(annotation)
            if not frames:
                skipped.append(f"{asset.id}: no evidence_frames")
                continue
            if not asset.source_artifact_id:
                skipped.append(f"{asset.id}: no source_artifact_id")
                continue
            artifact = session.get(ArtifactRow, asset.source_artifact_id)
            if artifact is None:
                skipped.append(f"{asset.id}: source artifact missing")
                continue
            video_url = _video_url_for(artifact, oss_client, upload_prefix)
            if not video_url:
                skipped.append(f"{asset.id}: no resolvable OSS video URL")
                continue

            assets_with_frames += 1
            frames_planned += len(frames)
            images: list[dict[str, Any]] = []
            extract_failed: str | None = None
            for idx, time_sec in enumerate(frames):
                key = _keyframe_key(upload_prefix, asset.id, idx)
                image_uri = f"s3://{bucket}/{key}"
                images.append({"time": time_sec, "image_url": image_uri})
                if not apply:
                    print(f"  PLAN {asset.id} frame[{idx}] @ {time_sec:.3f}s -> {key}", file=out)
                    continue
                if _object_exists(oss_client, key):
                    frames_reused += 1
                    continue
                try:
                    with tempfile.TemporaryDirectory() as tmpdir:
                        frame_path = Path(tmpdir) / f"{idx}.jpg"
                        _extract_frame(video_url=video_url, time_sec=time_sec, out_path=frame_path)
                        _upload_jpg(oss_client, frame_path, key)
                    frames_rendered += 1
                except Exception as exc:  # one bad frame (e.g. b-roll bytes not in OSS) must not abort the whole run
                    extract_failed = f"frame[{idx}]@{time_sec:.1f}s: {str(exc).splitlines()[0][:100]}"
                    break

            if apply:
                if extract_failed is not None:
                    skipped.append(f"{asset.id}: {extract_failed}")
                    continue
                canonical = dict(ann_row.canonical or {})
                canonical["evidence_frame_images"] = images
                # Validate the round-trip before persisting (out-of-bounds frames
                # would have already failed _coerce; this re-checks the merged dict).
                if _coerce_annotation_v4(canonical) is None:
                    skipped.append(f"{asset.id}: merged canonical failed AnnotationV4 validation; not written")
                    continue
                ann_row.canonical = canonical
                images_written += 1
                session.commit()  # per-asset commit so a later failure can't lose prior progress
        if apply:
            session.commit()

    print(f"{mode} evidence-frame keyframe generation", file=out)
    print(f"annotated assets with evidence_frames: {assets_with_frames}", file=out)
    print(f"frames planned: {frames_planned}", file=out)
    if apply:
        print(f"frames rendered+uploaded: {frames_rendered}", file=out)
        print(f"frames reused (already in OSS): {frames_reused}", file=out)
        print(f"annotations updated (evidence_frame_images): {images_written}", file=out)
    print(f"assets skipped: {len(skipped)}", file=out)
    for message in skipped[:50]:
        print(f"  - {message}", file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Render+upload+write. Default is dry-run (plan only).")
    parser.add_argument("--limit", type=int, default=0, help="Max assets to process (0 = no limit).")
    parser.add_argument(
        "--api-keys",
        type=Path,
        default=_default_api_keys(),
        help="api_keys.json with Aliyun OSS credentials (default: <repo>/.data/api_keys.json).",
    )
    parser.add_argument(
        "--bucket",
        default=os.getenv("CUTAGENT_LEGACY_OBJECTSTORE_BUCKET") or DEFAULT_BUCKET,
        help=f"Legacy OSS bucket (default: {DEFAULT_BUCKET}).",
    )
    parser.add_argument(
        "--upload-prefix",
        default=os.getenv("CUTAGENT_LEGACY_UPLOAD_PREFIX", DEFAULT_UPLOAD_PREFIX),
        help=f"Upload prefix (default: {DEFAULT_UPLOAD_PREFIX}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    upload_prefix = args.upload_prefix.strip("/") + "/"

    _bridge_oss_env(_load_api_keys(args.api_keys))
    from packages.migrations.legacy_asset_clients import LegacyOssClient

    oss_client = LegacyOssClient.from_env(bucket=args.bucket)

    return run(
        apply=bool(args.apply),
        limit=max(0, int(args.limit)),
        bucket=args.bucket,
        upload_prefix=upload_prefix,
        oss_client=oss_client,
    )


if __name__ == "__main__":
    raise SystemExit(main())
