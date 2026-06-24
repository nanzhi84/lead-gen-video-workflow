"""Deterministic cover-frame selection: pure scoring + selection orchestration.

The pure ``score_portrait_frame`` is exercised with hand-built ``FaceDetection``
objects (no cv2 / no ffmpeg). The ``select_best_portrait_frame`` orchestration is
exercised by stubbing the per-frame scorer + frame extraction so the test stays
deterministic and key-free.
"""

from __future__ import annotations

from packages.media.annotation.sensors import FaceDetection
from packages.media import cover_frame
from packages.media.cover_frame import score_portrait_frame, select_best_portrait_frame


def _face(x, y, w, h, *, score=0.9, landmarks=None):
    """Build a FaceDetection; default landmarks are a level, symmetric (frontal) face."""
    if landmarks is None:
        cx = x + w / 2
        eye_y = y + h * 0.4
        landmarks = (
            (cx - w * 0.2, eye_y),  # right eye
            (cx + w * 0.2, eye_y),  # left eye
            (cx, y + h * 0.55),  # nose
            (cx - w * 0.15, y + h * 0.75),  # right mouth corner
            (cx + w * 0.15, y + h * 0.75),  # left mouth corner
        )
    return FaceDetection(bbox=(x, y, w, h), score=score, landmarks=landmarks)


# ---- score_portrait_frame (pure) -------------------------------------------------


def test_zero_faces_returns_none():
    assert score_portrait_frame([], (1000, 1000), 150.0) is None


def test_multi_qualifying_faces_returns_none():
    # Two genuine subjects (both clear the gate) -> not a clean portrait.
    faces = [_face(200, 300, 300, 300), _face(600, 300, 300, 300)]
    assert score_portrait_frame(faces, (1000, 1000), 150.0) is None


def test_tiny_face_below_gate_returns_none():
    # 40px on a 1000px short side is below min_face_frac=0.05 (=50px) -> no qualifier.
    assert score_portrait_frame([_face(480, 480, 40, 40)], (1000, 1000), 150.0) is None


def test_centered_face_beats_edge_face():
    centered = score_portrait_frame([_face(350, 350, 300, 300)], (1000, 1000), 150.0)
    edge = score_portrait_frame([_face(680, 350, 300, 300)], (1000, 1000), 150.0)
    assert centered is not None and edge is not None
    assert centered > edge


def test_larger_face_in_band_beats_small_qualifier():
    big = score_portrait_frame([_face(350, 350, 300, 300)], (1000, 1000), 150.0)
    small = score_portrait_frame([_face(450, 450, 100, 100)], (1000, 1000), 150.0)
    assert big is not None and small is not None
    assert big > small


def test_sharper_face_beats_blurry():
    sharp = score_portrait_frame([_face(350, 350, 300, 300)], (1000, 1000), 250.0)
    blurry = score_portrait_frame([_face(350, 350, 300, 300)], (1000, 1000), 25.0)
    assert sharp is not None and blurry is not None
    assert sharp > blurry


def test_frontal_face_beats_profile():
    frontal = score_portrait_frame([_face(350, 350, 300, 300)], (1000, 1000), 150.0)
    # Profile: nose shoved toward the right eye -> strong left/right asymmetry.
    cx = 500
    profile_landmarks = (
        (cx - 60, 470),  # right eye
        (cx + 60, 470),  # left eye
        (cx - 50, 520),  # nose pushed off-center
        (cx - 40, 575),
        (cx + 40, 575),
    )
    profile = score_portrait_frame(
        [_face(350, 350, 300, 300, landmarks=profile_landmarks)], (1000, 1000), 150.0
    )
    assert frontal is not None and profile is not None
    assert frontal > profile


def test_good_face_score_in_unit_range():
    value = score_portrait_frame([_face(350, 350, 300, 300)], (1000, 1000), 250.0)
    assert value is not None
    assert 0.0 <= value <= 1.0


# ---- select_best_portrait_frame (orchestration) ----------------------------------


def test_select_picks_highest_scoring_frame(monkeypatch, tmp_path):
    frames = [(0.5, "/f/a.jpg"), (1.5, "/f/b.jpg"), (2.5, "/f/c.jpg")]
    monkeypatch.setattr(cover_frame, "extract_frames_for_times", lambda *a, **k: frames)
    scores = {"/f/a.jpg": 0.3, "/f/b.jpg": 0.82, "/f/c.jpg": 0.51}
    monkeypatch.setattr(cover_frame, "_score_frame_path", lambda path, **k: scores[path])

    best = select_best_portrait_frame("video.mp4", 3.0, temp_dir=str(tmp_path))

    assert best is not None
    assert best.time_sec == 1.5
    assert abs(best.score - 0.82) < 1e-9


def test_select_returns_none_when_no_frame_has_a_face(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cover_frame, "extract_frames_for_times", lambda *a, **k: [(0.5, "/f/a.jpg")]
    )
    monkeypatch.setattr(cover_frame, "_score_frame_path", lambda path, **k: None)
    assert select_best_portrait_frame("video.mp4", 1.0, temp_dir=str(tmp_path)) is None


def test_select_returns_none_when_no_frames_extracted(monkeypatch, tmp_path):
    monkeypatch.setattr(cover_frame, "extract_frames_for_times", lambda *a, **k: [])
    assert select_best_portrait_frame("video.mp4", 5.0, temp_dir=str(tmp_path)) is None


# ---- sampling ---------------------------------------------------------------------


def test_sample_times_bounded_and_inside_video():
    times = cover_frame._cover_sample_times(60.0, 30)
    assert 1 <= len(times) <= 30
    assert all(0.0 <= t <= 60.0 for t in times)
    assert times == sorted(times)


def test_sample_times_zero_duration_is_origin():
    assert cover_frame._cover_sample_times(0.0, 30) == [0.0]
