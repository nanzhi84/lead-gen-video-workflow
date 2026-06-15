"""Tests for the V4 assembler (run_annotation_v4) with fully injected V4Deps.

No real ffmpeg / scenedetect / silero / VLM: every dependency is a stub, so these
tests cover orchestration, classified retries, and aggregation deterministically.
"""

from __future__ import annotations

import json

from packages.core.contracts import AnnotationStatus, UsageRole
from packages.media.annotation.errors import RuntimeVLMError, SemanticError
from packages.media.annotation.pipeline import V4Config, V4Deps, run_annotation_v4


def _segment(start: float, end: float, *, role: str = "cover", lip_sync: bool = False) -> dict:
    return {
        "start": start,
        "end": end,
        "semantics": {"subject_type": "product", "scene_type": "studio", "action": "demo"},
        "visual": {"shot_scale": "medium", "camera_motion": "static", "composition": "centered"},
        "usage": {
            "recommended_for_lip_sync": lip_sync,
            "recommended_for_voiceover": True,
            "voiceover_only": True,
            "role": role,
        },
        "retrieval": {"summary": "product demo", "keywords": ["demo"], "retrieval_sentence": "demo"},
        "confidence": 0.9,
    }


def _vlm_response_for_window(window_start: float, window_end: float) -> str:
    return json.dumps({"segments": [_segment(window_start, window_end)]})


def _frames_stub(video_path, sample_times, *, temp_dir, max_long_side=1024):
    # No real extraction; return (time, fake_path) tuples without touching disk.
    return [(round(float(t), 3), f"{temp_dir}/f{i}.jpg") for i, t in enumerate(sample_times)]


def _base_deps(vlm_call) -> V4Deps:
    return V4Deps(
        detect_shot_cuts=lambda _vp: [],
        detect_speech_islands=lambda _vp: [],
        detect_quality_events=lambda _vp: [],
        extract_frames=_frames_stub,
        vlm_call=vlm_call,
        resolve_asr_text=lambda _vp: "全片台本",
    )


def test_pipeline_completed_with_semantics():
    def vlm_call(prompt, frames):
        # Single-window 4s clip -> one window [0,4].
        return _vlm_response_for_window(0.0, 4.0)

    ann = run_annotation_v4(
        asset_id="asset1",
        case_id="case1",
        material_type="broll",
        video_path="/fake/video.mp4",
        duration=4.0,
        deps=_base_deps(vlm_call),
        cfg=V4Config(),
    )
    assert ann.meta.annotation_status == AnnotationStatus.completed
    assert len(ann.clips) == 1
    clip = ann.clips[0]
    assert clip.semantics.action == "demo"
    assert clip.usage.role == UsageRole.cover
    # role != avoid -> a usage window is produced.
    assert len(ann.usage_windows) == 1
    assert ann.evidence_frames  # midpoints collected
    assert isinstance(ann.quality_report, dict)


def test_pipeline_quality_events_assembled_from_sensors():
    deps = _base_deps(lambda p, f: _vlm_response_for_window(0.0, 4.0))
    deps.detect_quality_events = lambda _vp: [
        {"event_type": "blur", "start": 0.5, "end": 1.0, "risk_tier": "soft"}
    ]
    ann = run_annotation_v4(
        asset_id="a",
        case_id="c",
        material_type="broll",
        video_path="/fake.mp4",
        duration=4.0,
        deps=deps,
        cfg=V4Config(),
    )
    assert ann.meta.annotation_status == AnnotationStatus.completed
    assert len(ann.quality_events) == 1
    assert ann.quality_events[0].event_type.value == "blur"
    assert ann.quality_events[0].source == "sensor"
    assert ann.quality_events[0].event_id  # auto-filled


def test_pipeline_schema_error_retries_then_fails():
    calls = {"n": 0}

    def vlm_call(prompt, frames):
        calls["n"] += 1
        return "not json"  # always a SchemaError

    cfg = V4Config(fmt_max_retries=2)
    ann = run_annotation_v4(
        asset_id="a",
        case_id="c",
        material_type="broll",
        video_path="/fake.mp4",
        duration=4.0,
        deps=_base_deps(vlm_call),
        cfg=cfg,
    )
    # FAILED object returned, never raised; clips/usage empty (no degraded annotation).
    assert ann.meta.annotation_status == AnnotationStatus.failed
    assert ann.clips == []
    assert ann.usage_windows == []
    assert ann.quality_report == {}
    # initial try + fmt_max_retries retries = 3 calls (bounded, not unbounded).
    assert calls["n"] == cfg.fmt_max_retries + 1


def test_pipeline_schema_error_recovers_after_retry():
    calls = {"n": 0}

    def vlm_call(prompt, frames):
        calls["n"] += 1
        if calls["n"] == 1:
            return "garbage"  # first SchemaError
        return _vlm_response_for_window(0.0, 4.0)

    ann = run_annotation_v4(
        asset_id="a",
        case_id="c",
        material_type="broll",
        video_path="/fake.mp4",
        duration=4.0,
        deps=_base_deps(vlm_call),
        cfg=V4Config(fmt_max_retries=2),
    )
    assert ann.meta.annotation_status == AnnotationStatus.completed
    assert len(ann.clips) == 1
    assert calls["n"] == 2


def test_pipeline_runtime_error_backs_off_bounded():
    calls = {"n": 0}
    sleeps: list[float] = []

    def vlm_call(prompt, frames):
        calls["n"] += 1
        raise RuntimeVLMError("rate limited")

    deps = _base_deps(vlm_call)
    deps.sleep = lambda s: sleeps.append(s)
    cfg = V4Config(rt_max_retries=3)
    ann = run_annotation_v4(
        asset_id="a",
        case_id="c",
        material_type="broll",
        video_path="/fake.mp4",
        duration=4.0,
        deps=deps,
        cfg=cfg,
    )
    assert ann.meta.annotation_status == AnnotationStatus.failed
    # initial + rt_max_retries = 4 calls; exponential backoff sleeps 1,2,4.
    assert calls["n"] == cfg.rt_max_retries + 1
    assert sleeps == [1.0, 2.0, 4.0]


def test_pipeline_semantic_error_resamples_denser():
    calls = {"n": 0}
    budgets: list[int] = []

    def frames_stub(video_path, sample_times, *, temp_dir, max_long_side=1024):
        budgets.append(len(sample_times))
        return _frames_stub(video_path, sample_times, temp_dir=temp_dir)

    def vlm_call(prompt, frames):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SemanticError("coverage gap")
        return _vlm_response_for_window(0.0, 4.0)

    deps = _base_deps(vlm_call)
    deps.extract_frames = frames_stub
    ann = run_annotation_v4(
        asset_id="a",
        case_id="c",
        material_type="broll",
        video_path="/fake.mp4",
        duration=4.0,
        deps=deps,
        cfg=V4Config(sem_max_retries=2),
    )
    assert ann.meta.annotation_status == AnnotationStatus.completed
    # second sample is denser than the first (density_level incremented).
    assert len(budgets) == 2
    assert budgets[1] > budgets[0]


def _portrait_segment(start: float, end: float) -> dict:
    """A clean portrait segment whose ONLY possible blocker is multi_face."""
    return {
        "start": start,
        "end": end,
        "semantics": {
            "subject_type": "person",
            "gaze_to_camera": True,
            "mouth_visible": True,
            "mouth_moving": True,
            "speaker_intent": "explain",
            "speech_action_alignment": "match",
            "retake_cue": "none",
        },
        "visual": {"shot_scale": "medium", "camera_motion": "static", "composition": "centered"},
        "usage": {
            "recommended_for_lip_sync": True,
            "recommended_for_voiceover": True,
            "voiceover_only": False,
            "role": "main",
        },
        "retrieval": {"summary": "talking head", "keywords": ["talk"], "retrieval_sentence": "talk"},
        "confidence": 0.9,
    }


def test_pipeline_portrait_two_face_frame_yields_multi_face_blocker():
    """A window whose CV multi-face sensor reports 2 faces sets face_count_max=2 and
    makes report._clip_blockers emit a multi_face blocker (the deterministic gate)."""
    from packages.media.annotation.report import _clip_blockers

    deps = _base_deps(lambda p, f: json.dumps({"segments": [_portrait_segment(0.0, 4.0)]}))
    # Deterministic CV sensor: this window has a 2-face frame (mirror/reflection).
    deps.detect_max_faces = lambda paths: 2

    ann = run_annotation_v4(
        asset_id="a",
        case_id="c",
        material_type="portrait",
        video_path="/fake.mp4",
        duration=4.0,
        deps=deps,
        cfg=V4Config(),
    )
    assert ann.meta.annotation_status == AnnotationStatus.completed
    assert len(ann.clips) == 1
    clip = ann.clips[0]
    # Authoritative CV source set face_count_max even though the VLM never volunteered it.
    assert clip.semantics.face_count_max == 2
    blockers = _clip_blockers(clip.model_dump(), hard_event=False)
    assert "multi_face" in blockers
    # The clean single-face counterpart has no multi_face blocker.
    single = clip.model_copy(deep=True)
    single.semantics.face_count_max = 1
    assert "multi_face" not in _clip_blockers(single.model_dump(), hard_event=False)


def test_pipeline_broll_does_not_run_multi_face_sensor():
    """B-roll windows never invoke the portrait-only multi-face sensor."""
    called = {"n": 0}

    def _detect(paths):
        called["n"] += 1
        return 2

    deps = _base_deps(lambda p, f: _vlm_response_for_window(0.0, 4.0))
    deps.detect_max_faces = _detect
    ann = run_annotation_v4(
        asset_id="a",
        case_id="c",
        material_type="broll",
        video_path="/fake.mp4",
        duration=4.0,
        deps=deps,
        cfg=V4Config(),
    )
    assert ann.meta.annotation_status == AnnotationStatus.completed
    assert called["n"] == 0
    assert ann.clips[0].semantics.face_count_max is None


def test_pipeline_zero_duration_is_empty_completed():
    ann = run_annotation_v4(
        asset_id="a",
        case_id="c",
        material_type="broll",
        video_path="/fake.mp4",
        duration=0.0,
        deps=_base_deps(lambda p, f: _vlm_response_for_window(0.0, 4.0)),
        cfg=V4Config(),
    )
    # duration<=0 -> no windows -> no clips, but a valid COMPLETED annotation.
    assert ann.meta.annotation_status == AnnotationStatus.completed
    assert ann.clips == []
