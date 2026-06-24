"""Deterministic best-portrait-frame selection for the AI cover.

Picks the most cover-worthy human frame from a (clean, subtitle-free, b-roll-free)
video by densely sampling frames and scoring each one with the YuNet face sensor +
a Laplacian sharpness measure — no VLM, no paid call. The scoring favours one large,
centered, sharp, frontal face and rejects multi-subject / faceless frames.

Discipline mirrors ``annotation/sensors``: ``score_portrait_frame`` is the pure
core (hand-built detections in, score out); ``select_best_portrait_frame`` does the
ffmpeg + cv2 IO and is fail-open (cv2/ffmpeg missing or no usable face -> ``None``
so the caller falls back to a midpoint frame).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from packages.media.annotation.sensors import FaceDetection, detect_faces
from packages.media.annotation.sensors.frames import extract_frames_for_times

_DEFAULT_MIN_FACE_FRAC = 0.05
_DEFAULT_N_MAX = 30
_DEFAULT_CANDIDATE_LONG_SIDE = 720
_MIN_STRIDE_SEC = 0.5
_EDGE_GUARD_SEC = 0.1

# Ideal face-area band (fraction of the whole frame) and centering targets.
_SIZE_BAND_LO = 0.05
_SIZE_BAND_HI = 0.30
_CENTER_X_TARGET = 0.5
_CENTER_Y_TARGET = 0.40  # face slightly above the frame center reads well on a cover
# Laplacian variance at/above which a face crop counts as fully sharp (60 is the
# cv_quality blur floor; 200 is "clearly sharp").
_SHARP_FULL = 200.0

# Score weights (sum to 1.0).
_W_SIZE = 0.25
_W_CENTER = 0.20
_W_SHARP = 0.25
_W_FRONTAL = 0.20
_W_CONF = 0.10


@dataclass(frozen=True)
class BestPortraitFrame:
    time_sec: float
    score: float


def score_portrait_frame(
    faces: list[FaceDetection],
    frame_wh: tuple[int, int],
    sharpness: float,
    *,
    min_face_frac: float = _DEFAULT_MIN_FACE_FRAC,
) -> float | None:
    """Score a single frame's cover-worthiness from its face detections.

    Returns ``None`` when the frame has no qualifying face or has 2+ qualifying
    faces (multi-subject / reflection — not a clean portrait). Otherwise returns a
    weighted score in ``[0, 1]`` for the single dominant face.
    """
    width, height = int(frame_wh[0]), int(frame_wh[1])
    if width <= 0 or height <= 0:
        return None
    min_side = min(width, height) * float(min_face_frac)
    qualifying = [f for f in faces if min(f.bbox[2], f.bbox[3]) >= min_side]
    if len(qualifying) != 1:
        return None
    face = qualifying[0]
    size = _size_score(face, width, height)
    center = _center_score(face, width, height)
    sharp = min(1.0, max(0.0, float(sharpness)) / _SHARP_FULL)
    frontal = _frontal_score(face)
    conf = _clamp01(face.score)
    return (
        _W_SIZE * size
        + _W_CENTER * center
        + _W_SHARP * sharp
        + _W_FRONTAL * frontal
        + _W_CONF * conf
    )


def select_best_portrait_frame(
    video_path: str,
    duration_sec: float,
    *,
    temp_dir: str,
    n_max: int = _DEFAULT_N_MAX,
    candidate_long_side: int = _DEFAULT_CANDIDATE_LONG_SIDE,
    min_face_frac: float = _DEFAULT_MIN_FACE_FRAC,
) -> BestPortraitFrame | None:
    """Densely sample ``video_path`` and return the highest-scoring portrait frame,
    or ``None`` when no frame has a usable single face (caller falls back)."""
    sample_times = _cover_sample_times(duration_sec, n_max)
    if not sample_times:
        return None
    try:
        frames = extract_frames_for_times(
            video_path, sample_times, temp_dir=temp_dir, max_long_side=candidate_long_side
        )
    except Exception:  # fail-open: ffmpeg unavailable / decode failure
        return None
    best: BestPortraitFrame | None = None
    for time_sec, path in frames:
        score = _score_frame_path(path, min_face_frac=min_face_frac)
        if score is None:
            continue
        if best is None or score > best.score:
            best = BestPortraitFrame(time_sec=float(time_sec), score=float(score))
    return best


def _score_frame_path(path: str, *, min_face_frac: float = _DEFAULT_MIN_FACE_FRAC) -> float | None:
    """Read a frame file, detect faces, and score it. fail-open returns ``None``."""
    try:
        import cv2  # type: ignore
    except Exception:  # pragma: no cover - cv2 missing
        return None
    image = cv2.imread(str(path))
    if image is None:
        return None
    faces = detect_faces(image)
    if not faces:
        return None
    height, width = image.shape[:2]
    dominant = max(faces, key=lambda f: f.bbox[2] * f.bbox[3])
    sharpness = _face_crop_sharpness(cv2, image, dominant.bbox)
    return score_portrait_frame(faces, (width, height), sharpness, min_face_frac=min_face_frac)


def _cover_sample_times(duration_sec: float, n_max: int) -> list[float]:
    """Evenly spaced sample times inside ``[edge, duration-edge]``, capped at ``n_max``."""
    duration = float(duration_sec or 0.0)
    if duration <= 0:
        return [0.0]
    lo = _EDGE_GUARD_SEC
    hi = max(_EDGE_GUARD_SEC, duration - _EDGE_GUARD_SEC)
    if hi <= lo:
        return [round(max(0.0, duration / 2.0), 3)]
    stride = max(_MIN_STRIDE_SEC, duration / float(n_max))
    times: list[float] = []
    point = lo
    while point <= hi + 1e-9 and len(times) < n_max:
        times.append(round(point, 3))
        point += stride
    return times


def _size_score(face: FaceDetection, width: int, height: int) -> float:
    frac = (face.bbox[2] * face.bbox[3]) / float(width * height)
    if frac <= 0:
        return 0.0
    if frac < _SIZE_BAND_LO:
        return frac / _SIZE_BAND_LO
    if frac <= _SIZE_BAND_HI:
        return 1.0
    # Above the band: decay toward (but not below) a floor as the face overfills.
    return max(0.3, 1.0 - (frac - _SIZE_BAND_HI) / _SIZE_BAND_HI * 0.7)


def _center_score(face: FaceDetection, width: int, height: int) -> float:
    cx = (face.bbox[0] + face.bbox[2] / 2.0) / float(width)
    cy = (face.bbox[1] + face.bbox[3] / 2.0) / float(height)
    horiz = 1.0 - min(1.0, abs(cx - _CENTER_X_TARGET) / 0.5)
    vert = 1.0 - min(1.0, abs(cy - _CENTER_Y_TARGET) / 0.5)
    return 0.6 * horiz + 0.4 * vert


def _frontal_score(face: FaceDetection) -> float:
    if len(face.landmarks) < 3:
        return 0.5
    right_eye, left_eye, nose = face.landmarks[0], face.landmarks[1], face.landmarks[2]
    face_w = float(face.bbox[2]) or 1.0
    asym = abs(_dist(left_eye, nose) - _dist(right_eye, nose)) / face_w
    tilt = abs(math.atan2(left_eye[1] - right_eye[1], (left_eye[0] - right_eye[0]) or 1e-6))
    return (1.0 - min(1.0, asym / 0.35)) * (1.0 - min(1.0, tilt / 0.5))


def _face_crop_sharpness(cv2, image, bbox: tuple[float, float, float, float]) -> float:
    x, y, w, h = bbox
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1 = min(image.shape[1], int(x + w))
    y1 = min(image.shape[0], int(y + h))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
