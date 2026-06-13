from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from packages.core.contracts import (
    MaterialUsageRankingItem,
    MaterialUsageRankingReport,
    MediaAssetRecord,
    SelectionLedgerEntry,
    SelectionMedium,
)


def material_usage_ranking_from_entries(
    *,
    entries: Sequence[SelectionLedgerEntry],
    assets: Mapping[str, MediaAssetRecord],
    kind: SelectionMedium,
    case_id: str | None,
    top_n: int,
) -> MaterialUsageRankingReport:
    run_latest: dict[str, datetime] = {}
    for entry in entries:
        current = run_latest.get(entry.run_id)
        if current is None or entry.created_at > current:
            run_latest[entry.run_id] = entry.created_at
    run_weights = {
        run_id: 1 / (index + 1)
        for index, run_id in enumerate(
            sorted(run_latest, key=lambda run_id: run_latest[run_id], reverse=True)
        )
    }

    by_asset: dict[str, list[SelectionLedgerEntry]] = {}
    for entry in entries:
        by_asset.setdefault(entry.asset_id, []).append(entry)

    items: list[MaterialUsageRankingItem] = []
    for asset_id, asset_entries in by_asset.items():
        run_ids = {entry.run_id for entry in asset_entries}
        last_used_at = max(entry.created_at for entry in asset_entries)
        recent_score = round(sum(run_weights[run_id] for run_id in run_ids), 6)
        items.append(
            MaterialUsageRankingItem(
                asset_id=asset_id,
                medium=kind,
                asset=assets.get(asset_id),
                task_use_count=len(run_ids),
                segment_use_count=len(asset_entries),
                last_used_at=last_used_at,
                recent_score=recent_score,
            )
        )

    items.sort(
        key=lambda item: (
            -item.recent_score,
            -item.task_use_count,
            -item.segment_use_count,
            -(item.last_used_at.timestamp() if item.last_used_at else 0),
            item.asset_id,
        )
    )
    bounded_top_n = max(1, min(top_n, 100))
    return MaterialUsageRankingReport(
        kind=kind,
        case_id=case_id,
        top_n=bounded_top_n,
        items=items[:bounded_top_n],
    )
