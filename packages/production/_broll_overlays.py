"""Canonical read boundary for a ``BrollPlanArtifact`` payload (#104).

``BrollOverlay`` is the single canonical structure for a planned B-roll insert.
New plans only write ``overlays``; this helper is the one place that knows how
to read a (possibly legacy) plan payload:

- when ``overlays`` is present it is authoritative;
- only when a legacy persisted plan predates overlays (it has the old dict
  ``segments`` but no ``overlays``) are overlays derived from those segments so
  old artifacts stay renderable.

The builder is intentionally lenient so a partial/legacy dict still yields a
typed overlay: ``timeline_start``/``timeline_end`` fall back to the legacy
``start_sec``/``end_sec`` field names, and a positional ``overlay_id`` is
synthesised when one is missing.
"""

from __future__ import annotations

from typing import Any

from packages.core.contracts.artifacts import BrollOverlay


def broll_overlays_from_plan(plan: dict[str, Any] | None) -> list[BrollOverlay]:
    """Return the canonical typed B-roll overlays for a plan payload."""
    payload = plan or {}
    items = payload.get("overlays")
    if not (isinstance(items, list) and items):
        # Legacy fallback: derive from the pre-#104 dict ``segments`` shape.
        items = payload.get("segments")
    if not isinstance(items, list):
        return []
    overlays: list[BrollOverlay] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        overlays.append(_overlay_from_item(item, index))
    return overlays


def _overlay_from_item(item: dict[str, Any], index: int) -> BrollOverlay:
    return BrollOverlay(
        overlay_id=str(item.get("overlay_id") or f"broll_{index + 1}"),
        asset_id=str(item.get("asset_id") or ""),
        clip_id=item.get("clip_id"),
        # Canonical overlays use timeline_start/timeline_end; legacy segments
        # used start_sec/end_sec — accept either so old plans keep working.
        timeline_start=float(item.get("timeline_start", item.get("start_sec", 0)) or 0),
        timeline_end=float(item.get("timeline_end", item.get("end_sec", 0)) or 0),
        source_start=float(item.get("source_start", 0) or 0),
        source_end=float(item.get("source_end", 0) or 0),
        reason=str(item.get("reason") or ""),
        confidence=float(item.get("confidence", 0) or 0),
        matched_keywords=list(item.get("matched_keywords") or []),
        scene_name=item.get("scene_name"),
        diversity_key=item.get("diversity_key") or None,
    )
