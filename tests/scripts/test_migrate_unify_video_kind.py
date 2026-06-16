from __future__ import annotations

from packages.core.contracts import (
    AnnotationMetaV4,
    AnnotationV4,
    ClipRetrievalV4,
    ClipSemanticsV4,
    ClipUsageV4,
    ClipV4,
    UsageRole,
)
from scripts.migrate_unify_video_kind import plan_unify


def _clip(
    segment_id: str,
    start: float,
    end: float,
    *,
    role: UsageRole = UsageRole.main,
    lip_sync: bool = True,
    face_count_max: int | None = 1,
) -> ClipV4:
    return ClipV4(
        segment_id=segment_id,
        start=start,
        end=end,
        duration=end - start,
        semantics=ClipSemanticsV4(scene_type="scene", face_count_max=face_count_max),
        usage=ClipUsageV4(role=role, recommended_for_lip_sync=lip_sync),
        retrieval=ClipRetrievalV4(
            summary=segment_id,
            keywords=[segment_id],
            retrieval_sentence=segment_id,
        ),
        confidence=0.9,
    )


def _annotation(asset_id: str, clips: list[ClipV4]) -> AnnotationV4:
    return AnnotationV4(
        meta=AnnotationMetaV4(
            asset_id=asset_id,
            case_id="case_demo",
            material_type="portrait",
            duration=20.0,
        ),
        clips=clips,
        quality_report={"usable_ratio": 1.0},
    )


def test_portrait_with_usable_clip():
    plan = plan_unify(
        [("asset_portrait", "portrait")],
        {"asset_portrait": _annotation("asset_portrait", [_clip("talk", 1.0, 4.0)])},
    )

    assert plan.reclassify == ["asset_portrait"]
    assert plan.rerun_candidates == []


def test_portrait_with_no_usable_clips():
    plan = plan_unify(
        [("asset_portrait", "portrait")],
        {
            "asset_portrait": _annotation(
                "asset_portrait",
                [_clip("cover", 1.0, 4.0, role=UsageRole.cover, lip_sync=False)],
            )
        },
    )

    assert plan.reclassify == ["asset_portrait"]
    assert plan.rerun_candidates == [("asset_portrait", "no lip-sync-usable clip")]


def test_broll_reclassify_no_rerun():
    plan = plan_unify(
        [("asset_broll", "broll")],
        {
            "asset_broll": _annotation(
                "asset_broll",
                [_clip("cover", 1.0, 4.0, role=UsageRole.cover, lip_sync=False)],
            )
        },
    )

    assert plan.reclassify == ["asset_broll"]
    assert plan.rerun_candidates == []


def test_already_video_skipped():
    plan = plan_unify(
        [("asset_video", "video")],
        {"asset_video": _annotation("asset_video", [_clip("talk", 1.0, 4.0)])},
    )

    assert plan.reclassify == []
    assert plan.rerun_candidates == []


def test_portrait_no_annotation():
    plan = plan_unify([("asset_portrait", "portrait")], {"asset_portrait": None})

    assert plan.reclassify == ["asset_portrait"]
    assert plan.rerun_candidates == [("asset_portrait", "no annotation")]


def test_idempotent_all_video():
    plan = plan_unify(
        [("asset_video_1", "video"), ("asset_video_2", "video")],
        {
            "asset_video_1": _annotation("asset_video_1", [_clip("talk_1", 1.0, 4.0)]),
            "asset_video_2": _annotation("asset_video_2", [_clip("talk_2", 5.0, 9.0)]),
        },
    )

    assert plan.reclassify == []
    assert plan.rerun_candidates == []
