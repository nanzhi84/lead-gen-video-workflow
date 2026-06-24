from __future__ import annotations

import cv2  # type: ignore
import numpy as np  # type: ignore

from packages.media.annotation.sensors import (
    count_faces_in_image,
    detect_faces,
    max_faces_in_frame_paths,
    reset_detector_cache,
)
from tests.media.annotation.fixtures import make_blank_image, make_face_image


def _draw_face(img, cx, cy, s=1.0):
    cv2.ellipse(img, (cx, cy), (int(110 * s), int(140 * s)), 0, 0, 360, (180, 200, 230), -1)
    cv2.circle(img, (cx - 40, cy - 30), int(18 * s), (255, 255, 255), -1)
    cv2.circle(img, (cx + 40, cy - 30), int(18 * s), (255, 255, 255), -1)
    cv2.circle(img, (cx - 40, cy - 30), int(8 * s), (40, 40, 40), -1)
    cv2.circle(img, (cx + 40, cy - 30), int(8 * s), (40, 40, 40), -1)
    cv2.ellipse(img, (cx, cy + 70), (int(45 * s), int(20 * s)), 0, 0, 180, (60, 60, 120), 4)


def test_count_faces_on_synthetic_single_face(tmp_path):
    reset_detector_cache()
    _path, img = make_face_image(tmp_path)
    assert count_faces_in_image(img) == 1


def test_count_faces_on_blank_is_zero(tmp_path):
    reset_detector_cache()
    _path, img = make_blank_image(tmp_path)
    assert count_faces_in_image(img) == 0


def test_count_faces_two_faces(tmp_path):
    reset_detector_cache()
    img = np.full((480, 960, 3), 210, dtype=np.uint8)
    _draw_face(img, 230, 250)
    _draw_face(img, 720, 250)
    assert count_faces_in_image(img) >= 2


def test_count_faces_none_image_is_zero():
    assert count_faces_in_image(None) == 0


def test_max_faces_in_frame_paths(tmp_path):
    reset_detector_cache()
    blank_path, _ = make_blank_image(tmp_path, name="b.png")
    face_path, _ = make_face_image(tmp_path, name="f.png")
    assert max_faces_in_frame_paths([str(blank_path), str(face_path)]) == 1
    assert max_faces_in_frame_paths([]) == 0


def test_detect_faces_exposes_geometry_for_synthetic_face(tmp_path):
    reset_detector_cache()
    _path, img = make_face_image(tmp_path)
    faces = detect_faces(img)
    assert len(faces) >= 1
    face = max(faces, key=lambda f: f.bbox[2] * f.bbox[3])
    x, y, w, h = face.bbox
    assert w > 0 and h > 0
    assert 0.0 < face.score <= 1.0
    assert len(face.landmarks) == 5
    assert all(len(point) == 2 for point in face.landmarks)


def test_detect_faces_blank_is_empty(tmp_path):
    reset_detector_cache()
    _path, img = make_blank_image(tmp_path)
    assert detect_faces(img) == []


def test_detect_faces_none_image_is_empty():
    assert detect_faces(None) == []


def test_count_faces_matches_qualifying_detections(tmp_path):
    # count_faces_in_image must be exactly the detect_faces results that clear the
    # min_face_frac gate -- locking the refactor that builds count on top of detect.
    reset_detector_cache()
    _path, img = make_face_image(tmp_path)
    min_side = min(img.shape[0], img.shape[1]) * 0.05
    qualifying = [f for f in detect_faces(img) if min(f.bbox[2], f.bbox[3]) >= min_side]
    assert count_faces_in_image(img) == len(qualifying)
