"""P1: the unified ``video`` material class runs the full sensor suite + a superset
VLM prompt, so one mixed clip yields both lip-sync-usable (A-roll) and cover-usable
(B-roll) segments — no human portrait/b-roll pre-classification at upload.

All dependencies are injected stubs (no real ffmpeg / VLM / silero).
"""

from __future__ import annotations

import json

from packages.core.contracts import AnnotationStatus
from packages.media.annotation._material import (
    is_video,
    material_class,
    runs_speech_and_face,
)
from packages.media.annotation.pipeline import V4Config, V4Deps, run_annotation_v4
from packages.media.annotation.vlm import build_window_prompt


def _frames_stub(video_path, sample_times, *, temp_dir, max_long_side=1024):
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


def _portrait_segment(start: float, end: float) -> dict:
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


def test_material_class_routes_three_ways():
    assert material_class("portrait") == "portrait"
    assert material_class("broll") == "broll"
    assert material_class("video") == "video"
    # asset kinds that never reach the visual pipeline still classify deterministically
    assert material_class("bgm") == "broll"
    assert is_video("video") and not is_video("portrait")
    # video + portrait run the speech/face sensors; dedicated b-roll does not
    assert runs_speech_and_face("video")
    assert runs_speech_and_face("portrait")
    assert not runs_speech_and_face("broll")


def test_video_runs_speech_and_face_and_merges_report():
    speech_called = {"n": 0}
    face_called = {"n": 0}

    def _speech(_vp):
        speech_called["n"] += 1
        return []

    def _faces(_paths):
        face_called["n"] += 1
        return 1

    deps = _base_deps(lambda _p, _f: json.dumps({"segments": [_portrait_segment(0.0, 4.0)]}))
    deps.detect_speech_islands = _speech
    deps.detect_max_faces = _faces

    ann = run_annotation_v4(
        asset_id="a",
        case_id="c",
        material_type="video",
        video_path="/fake.mp4",
        duration=4.0,
        deps=deps,
        cfg=V4Config(),
    )

    assert ann.meta.annotation_status == AnnotationStatus.completed
    # VAD speech islands + multi-face sensor BOTH run for the unified bucket
    # (a dedicated b-roll asset skips both — see test_pipeline_broll_*).
    assert speech_called["n"] >= 1
    assert face_called["n"] >= 1
    # Authoritative CV face count is recorded so P2 lip-sync gating can use it.
    assert ann.clips[0].semantics.face_count_max == 1
    # The merged quality report carries BOTH portrait and b-roll whole-clip metrics.
    assert "lip_sync_suitability_score" in ann.quality_report  # portrait metric
    assert "usable_ratio" in ann.quality_report  # b-roll metric


def test_video_prompt_is_superset_of_portrait_and_broll():
    video_prompt = build_window_prompt(
        material_type="video",
        window_start=0.0,
        window_end=4.0,
        sensor_signals={},
        full_asr_text="",
    )
    # Superset: it carries BOTH a portrait-only field (gaze_to_camera) and a
    # b-roll-only field (narrative_role), and asks the VLM to set lip-sync usage.
    assert "gaze_to_camera" in video_prompt
    assert "narrative_role" in video_prompt
    assert "recommended_for_lip_sync" in video_prompt

    # The dedicated portrait prompt does NOT carry the b-roll narrative_role guide.
    portrait_prompt = build_window_prompt(
        material_type="portrait",
        window_start=0.0,
        window_end=4.0,
        sensor_signals={},
        full_asr_text="",
    )
    assert "narrative_role" not in portrait_prompt
