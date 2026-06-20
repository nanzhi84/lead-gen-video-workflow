from __future__ import annotations

from packages.core.contracts import ArtifactKind, ArtifactRef
from packages.production.pipeline._timeline_grid import (
    align_broll_to_portrait_cuts,
    build_tracks,
    validate_timeline,
)


def _ref(artifact_id: str, kind: ArtifactKind = ArtifactKind.plan_broll) -> ArtifactRef:
    return ArtifactRef(artifact_id=artifact_id, kind=kind, uri=f"artifact://{artifact_id}")


def _segment(
    *,
    track_id: str = "broll",
    segment_id: str = "seg_1",
    start_sec: float = 0.0,
    end_sec: float = 1.0,
    timeline_start_frame: int | None = None,
    timeline_end_frame: int | None = None,
) -> dict:
    return {
        "track_id": track_id,
        "segment_id": segment_id,
        "asset_ref": _ref(f"{track_id}_{segment_id}"),
        "start_sec": start_sec,
        "end_sec": end_sec,
        "source_start_sec": start_sec,
        "source_end_sec": end_sec,
        "timeline_start_frame": timeline_start_frame,
        "timeline_end_frame": timeline_end_frame,
        "source_start_frame": None,
        "source_end_frame": None,
    }


def test_build_tracks_prefers_explicit_frame_grid_and_falls_back_to_seconds():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.123,
            end_sec=1.987,
            timeline_start_frame=0,
            timeline_end_frame=50,
        ),
        _segment(track_id="broll", segment_id="broll_1", start_sec=1.0, end_sec=2.0),
    ]

    tracks = build_tracks(raw_segments, fps=25)

    assert tracks[0].track_id == "portrait"
    assert tracks[0].timeline_start_frame == 0
    assert tracks[0].timeline_end_frame == 50
    assert tracks[0].source_start_frame == 3
    assert tracks[0].source_end_frame == 50
    assert tracks[1].track_id == "broll"
    assert tracks[1].timeline_start_frame == 25
    assert tracks[1].timeline_end_frame == 50
    assert tracks[1].pad_start == 0.0
    assert tracks[1].pad_end == 0.0


def test_align_broll_end_snaps_to_nearby_portrait_cut():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.0,
            end_sec=5.0,
            timeline_start_frame=0,
            timeline_end_frame=150,
        ),
        _segment(
            track_id="portrait",
            segment_id="portrait_2",
            start_sec=5.0,
            end_sec=10.0,
            timeline_start_frame=150,
            timeline_end_frame=300,
        ),
        _segment(
            track_id="broll",
            segment_id="broll_1",
            start_sec=3.0,
            end_sec=4.9,
        ),
    ]

    aligned = align_broll_to_portrait_cuts(raw_segments, fps=30, max_gap_frames=6)
    broll = next(segment for segment in aligned if segment["track_id"] == "broll")

    assert broll["timeline_start_frame"] == 90
    assert broll["timeline_end_frame"] == 150
    assert broll["source_start_frame"] == 90
    assert broll["source_end_frame"] == 147
    assert broll["end_sec"] == 5.0
    assert broll.get("pad_start", 0.0) == 0.0
    assert broll["pad_end"] == 0.1


def test_align_broll_start_does_not_snap_when_required_head_pad_is_visible():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_10",
            start_sec=55.5,
            end_sec=61.467,
            timeline_start_frame=1665,
            timeline_end_frame=1844,
        ),
        _segment(
            track_id="portrait",
            segment_id="portrait_11",
            start_sec=61.467,
            end_sec=67.9,
            timeline_start_frame=1844,
            timeline_end_frame=2037,
        ),
        _segment(
            track_id="broll",
            segment_id="broll_1",
            start_sec=61.898,
            end_sec=64.978,
        )
        | {
            "source_start_sec": 18.2,
            "source_end_sec": 21.28,
        },
    ]

    aligned = align_broll_to_portrait_cuts(raw_segments, fps=30, max_gap_frames=15)
    broll = next(segment for segment in aligned if segment["track_id"] == "broll")

    assert broll.get("timeline_start_frame") is None
    assert broll.get("timeline_end_frame") is None
    assert broll.get("source_start_frame") is None
    assert broll.get("source_end_frame") is None
    assert broll.get("pad_start", 0.0) == 0.0
    assert broll.get("pad_end", 0.0) == 0.0


def test_broll_start_does_not_snap_to_portrait_head_when_pad_exceeds_limit():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.0,
            end_sec=10.0,
            timeline_start_frame=0,
            timeline_end_frame=300,
        ),
        _segment(
            track_id="broll",
            segment_id="broll_1",
            start_sec=2.0,
            end_sec=5.0,
        )
        | {"source_start_sec": 5.0, "source_end_sec": 8.0},
    ]

    aligned = align_broll_to_portrait_cuts(
        raw_segments,
        fps=30,
        min_visible_aroll_frames=90,
    )
    broll = next(segment for segment in aligned if segment["track_id"] == "broll")

    assert broll.get("timeline_start_frame") is None
    assert broll.get("timeline_end_frame") is None
    assert broll.get("source_start_frame") is None
    assert broll.get("source_end_frame") is None
    assert broll.get("pad_start", 0.0) == 0.0
    assert broll.get("pad_end", 0.0) == 0.0


def test_broll_end_does_not_snap_to_portrait_tail_when_pad_exceeds_limit():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.0,
            end_sec=10.0,
            timeline_start_frame=0,
            timeline_end_frame=300,
        ),
        _segment(
            track_id="broll",
            segment_id="broll_1",
            start_sec=4.0,
            end_sec=8.0,
        )
        | {"source_start_sec": 12.0, "source_end_sec": 16.0},
    ]

    aligned = align_broll_to_portrait_cuts(
        raw_segments,
        fps=30,
        min_visible_aroll_frames=90,
    )
    broll = next(segment for segment in aligned if segment["track_id"] == "broll")

    assert broll.get("timeline_start_frame") is None
    assert broll.get("timeline_end_frame") is None
    assert broll.get("source_start_frame") is None
    assert broll.get("source_end_frame") is None
    assert broll.get("pad_start", 0.0) == 0.0
    assert broll.get("pad_end", 0.0) == 0.0


def test_broll_does_not_cover_whole_portrait_shot_when_pads_exceed_limit():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.0,
            end_sec=10.0,
            timeline_start_frame=0,
            timeline_end_frame=300,
        ),
        _segment(
            track_id="broll",
            segment_id="broll_1",
            start_sec=2.0,
            end_sec=8.0,
        )
        | {"source_start_sec": 5.0, "source_end_sec": 11.0},
    ]

    aligned = align_broll_to_portrait_cuts(
        raw_segments,
        fps=30,
        min_visible_aroll_frames=90,
    )
    broll = next(segment for segment in aligned if segment["track_id"] == "broll")

    assert broll.get("timeline_start_frame") is None
    assert broll.get("timeline_end_frame") is None
    assert broll.get("source_start_frame") is None
    assert broll.get("source_end_frame") is None
    assert broll.get("pad_start", 0.0) == 0.0
    assert broll.get("pad_end", 0.0) == 0.0


def test_broll_keeps_interior_window_when_visible_aroll_residuals_are_long_enough():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.0,
            end_sec=12.0,
            timeline_start_frame=0,
            timeline_end_frame=360,
        ),
        _segment(
            track_id="broll",
            segment_id="broll_1",
            start_sec=3.0,
            end_sec=9.0,
        )
        | {"source_start_sec": 5.0, "source_end_sec": 11.0},
    ]

    aligned = align_broll_to_portrait_cuts(
        raw_segments,
        fps=30,
        min_visible_aroll_frames=90,
    )
    broll = next(segment for segment in aligned if segment["track_id"] == "broll")

    assert broll.get("timeline_start_frame") is None
    assert broll.get("timeline_end_frame") is None


def test_broll_expansion_does_not_pull_source_when_residual_equals_threshold():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.0,
            end_sec=10.0,
            timeline_start_frame=0,
            timeline_end_frame=300,
        ),
        _segment(
            track_id="broll",
            segment_id="broll_1",
            start_sec=2.0,
            end_sec=8.0,
        )
        | {"source_start_sec": 5.0, "source_end_sec": 11.0},
    ]

    aligned = align_broll_to_portrait_cuts(raw_segments, fps=30)
    broll = next(segment for segment in aligned if segment["track_id"] == "broll")

    assert broll.get("timeline_start_frame") is None
    assert broll.get("timeline_end_frame") is None
    assert broll.get("source_start_frame") is None
    assert broll.get("source_end_frame") is None
    assert broll.get("pad_start", 0.0) == 0.0
    assert broll.get("pad_end", 0.0) == 0.0


def test_broll_head_residual_is_absorbed_with_pad_not_source_pull_when_safe():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.0,
            end_sec=10.0,
            timeline_start_frame=0,
            timeline_end_frame=300,
        ),
        _segment(
            track_id="broll",
            segment_id="broll_1",
            start_sec=0.1,
            end_sec=8.0,
        )
        | {"source_start_sec": 5.0, "source_end_sec": 12.9},
    ]

    aligned = align_broll_to_portrait_cuts(raw_segments, fps=30)
    broll = next(segment for segment in aligned if segment["track_id"] == "broll")

    assert broll["timeline_start_frame"] == 0
    assert broll["timeline_end_frame"] == 240
    assert broll["source_start_frame"] == 150
    assert broll["source_end_frame"] == 387
    assert broll["pad_start"] == 0.1
    assert broll.get("pad_end", 0.0) == 0.0


def test_broll_short_residual_is_not_absorbed_when_required_pad_is_visible():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.0,
            end_sec=10.0,
            timeline_start_frame=0,
            timeline_end_frame=300,
        ),
        _segment(
            track_id="broll",
            segment_id="broll_1",
            start_sec=1.5,
            end_sec=8.0,
        )
        | {"source_start_sec": 5.0, "source_end_sec": 11.5},
    ]

    aligned = align_broll_to_portrait_cuts(raw_segments, fps=30)
    broll = next(segment for segment in aligned if segment["track_id"] == "broll")

    assert broll.get("timeline_start_frame") is None
    assert broll.get("source_start_frame") is None
    assert broll.get("pad_start", 0.0) == 0.0


def test_broll_can_cover_whole_portrait_shot_with_safe_head_and_tail_pad():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.0,
            end_sec=3.0,
            timeline_start_frame=0,
            timeline_end_frame=90,
        ),
        _segment(
            track_id="broll",
            segment_id="broll_1",
            start_sec=0.1,
            end_sec=2.9,
        )
        | {"source_start_sec": 5.0, "source_end_sec": 7.8},
    ]

    aligned = align_broll_to_portrait_cuts(raw_segments, fps=30)
    broll = next(segment for segment in aligned if segment["track_id"] == "broll")

    assert broll["timeline_start_frame"] == 0
    assert broll["timeline_end_frame"] == 90
    assert broll["source_start_frame"] == 150
    assert broll["source_end_frame"] == 234
    assert broll["pad_start"] == 0.1
    assert broll["pad_end"] == 0.1


def test_broll_safe_head_pad_does_not_require_source_headroom():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.0,
            end_sec=10.0,
            timeline_start_frame=0,
            timeline_end_frame=300,
        ),
        _segment(
            track_id="broll",
            segment_id="broll_1",
            start_sec=0.1,
            end_sec=5.0,
        )
        | {"source_start_sec": 0.0, "source_end_sec": 4.9},
    ]

    aligned = align_broll_to_portrait_cuts(
        raw_segments,
        fps=30,
        min_visible_aroll_frames=90,
    )

    broll = next(segment for segment in aligned if segment["track_id"] == "broll")

    assert broll["timeline_start_frame"] == 0
    assert broll["timeline_end_frame"] == 150
    assert broll["source_start_frame"] == 0
    assert broll["source_end_frame"] == 147
    assert broll["pad_start"] == 0.1
    assert broll.get("pad_end", 0.0) == 0.0


def test_validate_timeline_reports_valid_grid_for_portrait_and_broll_tracks():
    raw_segments = [
        _segment(
            track_id="portrait",
            segment_id="portrait_1",
            start_sec=0.0,
            end_sec=2.0,
            timeline_start_frame=0,
            timeline_end_frame=50,
        ),
        _segment(track_id="broll", segment_id="broll_1", start_sec=0.5, end_sec=1.5),
        _segment(track_id="broll", segment_id="broll_2", start_sec=1.5, end_sec=2.0),
    ]

    validation = validate_timeline(raw_segments, fps=25, total_frames=50)

    assert validation.valid is True
    assert validation.checks == {
        "overlap": True,
        "negative_duration": True,
        "out_of_bounds": True,
    }


def test_validate_timeline_flags_overlap_per_track():
    raw_segments = [
        _segment(segment_id="broll_1", start_sec=0.0, end_sec=1.2),
        _segment(segment_id="broll_2", start_sec=1.0, end_sec=2.0),
    ]

    validation = validate_timeline(raw_segments, fps=25, total_frames=50)

    assert validation.valid is False
    assert validation.checks["overlap"] is False
    assert validation.checks["negative_duration"] is True
    assert validation.checks["out_of_bounds"] is True


def test_validate_timeline_flags_out_of_bounds():
    raw_segments = [_segment(start_sec=0.0, end_sec=2.1)]

    validation = validate_timeline(raw_segments, fps=25, total_frames=50)

    assert validation.valid is False
    assert validation.checks["out_of_bounds"] is False
    assert validation.checks["overlap"] is True
    assert validation.checks["negative_duration"] is True


def test_validate_timeline_flags_negative_duration():
    raw_segments = [_segment(start_sec=1.0, end_sec=1.0)]

    validation = validate_timeline(raw_segments, fps=25, total_frames=50)

    assert validation.valid is False
    assert validation.checks["negative_duration"] is False
    assert validation.checks["overlap"] is True
    assert validation.checks["out_of_bounds"] is True
