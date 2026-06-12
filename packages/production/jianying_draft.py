from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.core.storage.object_store import ObjectStore
from packages.media.video.ffmpeg import probe_media
from . import jianying_draft_json as jy_json


@dataclass(frozen=True)
class JianyingDraftInput:
    finished_video_id: str
    title: str
    video_path: Path
    audio_path: Path | None = None
    subtitle_path: Path | None = None
    duration_sec: float = 0
    template_id: str | None = None
    timeline_plan: dict[str, Any] | None = None
    narration_units: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class JianyingDraftBuild:
    package_uri: str
    sha256: str
    size_bytes: int
    draft_name: str
    draft_id: str
    tracks_summary: dict[str, int]
    manifest: dict[str, Any]


class JianyingDraftBuilder:
    def __init__(self, object_store: ObjectStore) -> None:
        self.object_store = object_store

    def build(self, source: JianyingDraftInput) -> JianyingDraftBuild:
        with tempfile.TemporaryDirectory(prefix="cutagent-jianying-") as directory:
            root = Path(directory) / "draft_root"
            draft_name = _safe_draft_name(source.title, source.finished_video_id)
            draft_id = str(uuid.uuid4()).upper()
            draft_dir = root / draft_name
            created_us = _now_us()
            (draft_dir / "Resources" / "video").mkdir(parents=True, exist_ok=True)
            (draft_dir / "Resources" / "audio").mkdir(parents=True, exist_ok=True)

            warnings: list[str] = []
            used_names: set[str] = set()
            video_path = _stage_media_file(source.video_path, draft_dir / "Resources" / "video", used_names, warnings)
            audio_path = (
                _stage_media_file(source.audio_path, draft_dir / "Resources" / "audio", used_names, warnings)
                if source.audio_path
                else None
            )
            video_info = probe_media(video_path)
            audio_info = probe_media(audio_path) if audio_path else None
            duration_us = max(
                _sec_to_us(source.duration_sec),
                _sec_to_us(video_info.duration_sec or 0),
                _sec_to_us(audio_info.duration_sec or 0) if audio_info else 0,
                1,
            )
            width = int(video_info.width or 1080)
            height = int(video_info.height or 1920)

            materials = jy_json.empty_materials()
            tracks: list[dict[str, Any]] = []
            speeds: list[dict[str, Any]] = []

            video_material = _video_material(video_path, duration_us, width, height)
            materials["videos"].append(video_material)
            main_segments = _main_video_segments(source, video_material["id"], duration_us)
            tracks.append(_track("video", "video", 0, main_segments))
            for segment in main_segments:
                speeds.append(_speed_material(segment["extra_material_refs"][0], segment["speed"]))

            broll_segments = _broll_segments(source, video_material["id"])
            if broll_segments:
                tracks.append(_track("video", "broll", 1, broll_segments))
                for segment in broll_segments:
                    speeds.append(_speed_material(segment["extra_material_refs"][0], segment["speed"]))

            if audio_path and audio_info:
                audio_duration_us = max(1, _sec_to_us(audio_info.duration_sec or source.duration_sec))
                audio_material = _audio_material(audio_path, audio_duration_us)
                materials["audios"].append(audio_material)
                audio_segment = _media_segment(audio_material["id"], 0, audio_duration_us, 0, audio_duration_us, volume=1.0)
                tracks.append(_track("audio", "audio", 0, [audio_segment]))
                speeds.append(_speed_material(audio_segment["extra_material_refs"][0], audio_segment["speed"]))

            subtitle_entries = jy_json.subtitle_entries(source.subtitle_path, source.narration_units)
            subtitle_segments: list[dict[str, Any]] = []
            for entry in subtitle_entries:
                material_id = uuid.uuid4().hex
                duration = max(1, int(entry["end_us"] - entry["start_us"]))
                materials["texts"].append(_text_material(material_id, entry["text"]))
                subtitle_segments.append(_text_segment(material_id, int(entry["start_us"]), duration))
            if subtitle_segments:
                tracks.append(_track("text", "subtitle", 15200, subtitle_segments))

            materials["speeds"] = speeds
            content = jy_json.draft_content(
                draft_id=draft_id,
                draft_name=draft_name,
                width=width,
                height=height,
                duration_us=duration_us,
                created_us=created_us,
                materials=materials,
                tracks=sorted(tracks, key=lambda item: item["segments"][0].get("render_index", 0) if item["segments"] else 0),
            )
            jy_json.dump_json(draft_dir / "draft_content.json", content)
            jy_json.ensure_supporting_files(draft_dir)
            folder_size = jy_json.folder_size_bytes(draft_dir)
            jy_json.dump_json(
                draft_dir / "draft_meta_info.json",
                jy_json.draft_meta(root, draft_dir, draft_name, draft_id, duration_us, folder_size, created_us),
            )
            jy_json.dump_json(
                root / "root_meta_info.json",
                jy_json.root_meta(root, draft_dir, draft_name, draft_id, duration_us, folder_size, created_us),
            )

            zip_path = Path(directory) / f"{draft_name}.zip"
            jy_json.zip_root(root, zip_path)
            stored = self.object_store.put_bytes(
                self.object_store.prepare_upload(zip_path.name, "jianying-drafts"),
                zip_path.read_bytes(),
            )
            tracks_summary = {
                "main_video": len(main_segments),
                "voice_audio": 1 if audio_path else 0,
                "subtitle_segments": len(subtitle_segments),
                "broll_segments": len(broll_segments),
                "overlay_tracks": 0,
                "cover_tracks": 0,
                "huazi_segments": 0,
            }
            manifest = {
                "finished_video_id": source.finished_video_id,
                "template_id": source.template_id or "default",
                "draft_name": draft_name,
                "draft_id": draft_id,
                "duration_us": duration_us,
                "tracks_summary": tracks_summary,
                "package_uri": stored.ref.uri,
                "assets": {
                    "video": [Path(video_path).name],
                    "audio": [Path(audio_path).name] if audio_path else [],
                    "subtitle": Path(source.subtitle_path).name if source.subtitle_path else None,
                },
                "warnings": warnings,
            }
            return JianyingDraftBuild(stored.ref.uri, stored.sha256, stored.size_bytes, draft_name, draft_id, tracks_summary, manifest)


def _safe_draft_name(title: str, task_id: str) -> str:
    base = re.sub(r'[\\/:*?"<>|]', "", (title or "").strip())
    base = re.sub(r"\s+", " ", base).strip() or "剪映草稿"
    if len(base) > 28:
        base = base[:28].rstrip()
    return f"{base}丨{task_id[:8]}"


def _now_us() -> int:
    return int(time.time() * 1_000_000)


def _sec_to_us(value: float | int | None) -> int:
    return int(round(float(value or 0) * 1_000_000))


def _frame_to_us(frame: int, fps: int) -> int:
    return int(float(frame) / float(fps or 30) * 1_000_000)


def _stage_media_file(source_path: Path, target_dir: Path, used_names: set[str], warnings: list[str]) -> str:
    source = Path(source_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"素材不存在: {source}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _unique_name(source.name, used_names)
    try:
        os.link(source, target)
    except Exception:
        try:
            shutil.copy2(source, target)
        except Exception as exc:
            warnings.append(f"素材复制失败，回退原路径: {source} ({exc})")
            return str(source)
    return str(target)


def _unique_name(original_name: str, used_names: set[str]) -> str:
    candidate = original_name
    stem = Path(original_name).stem
    suffix = Path(original_name).suffix
    index = 1
    while candidate in used_names:
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    used_names.add(candidate)
    return candidate


def _main_video_segments(source: JianyingDraftInput, material_id: str, duration_us: int) -> list[dict[str, Any]]:
    plan = source.timeline_plan or {}
    fps = int(plan.get("fps") or 30)
    segments = []
    for raw in plan.get("tracks") or []:
        if str(raw.get("track_id") or "").lower() != "portrait":
            continue
        start = _frame_to_us(int(raw.get("timeline_start_frame") or 0), fps)
        end = _frame_to_us(int(raw.get("timeline_end_frame") or 0), fps)
        source_start = _frame_to_us(int(raw.get("source_start_frame") or 0), fps)
        source_end = _frame_to_us(int(raw.get("source_end_frame") or raw.get("timeline_end_frame") or 0), fps)
        if end > start:
            segments.append(_media_segment(material_id, start, end - start, source_start, max(1, source_end - source_start), volume=0.0))
    return segments or [_media_segment(material_id, 0, duration_us, 0, duration_us, volume=0.0)]


def _broll_segments(source: JianyingDraftInput, material_id: str) -> list[dict[str, Any]]:
    plan = source.timeline_plan or {}
    fps = int(plan.get("fps") or 30)
    segments = []
    for raw in plan.get("tracks") or []:
        if str(raw.get("track_id") or "").lower() != "broll":
            continue
        start = _frame_to_us(int(raw.get("timeline_start_frame") or 0), fps)
        end = _frame_to_us(int(raw.get("timeline_end_frame") or 0), fps)
        source_start = _frame_to_us(int(raw.get("source_start_frame") or 0), fps)
        source_end = _frame_to_us(int(raw.get("source_end_frame") or raw.get("timeline_end_frame") or 0), fps)
        if end > start:
            segments.append(_media_segment(material_id, start, end - start, source_start, max(1, source_end - source_start), volume=0.0))
    return segments


def _media_segment(material_id: str, start: int, duration: int, source_start: int, source_duration: int, *, volume: float) -> dict[str, Any]:
    speed_id = uuid.uuid4().hex
    payload = _base_segment(material_id, start, duration)
    payload.update(
        {
            "source_timerange": {"start": int(source_start), "duration": int(source_duration)},
            "speed": 1.0,
            "volume": volume,
            "extra_material_refs": [speed_id],
            "is_tone_modify": False,
            "clip": _clip(),
            "uniform_scale": {"on": True, "value": 1.0},
        }
    )
    return payload


def _text_segment(material_id: str, start: int, duration: int) -> dict[str, Any]:
    payload = _base_segment(material_id, start, duration)
    payload.update(
        {
            "source_timerange": None,
            "speed": 1.0,
            "volume": 1.0,
            "extra_material_refs": [uuid.uuid4().hex],
            "is_tone_modify": False,
            "clip": _clip(transform_y=-0.8),
            "uniform_scale": {"on": True, "value": 1.0},
        }
    )
    return payload


def _base_segment(material_id: str, start: int, duration: int) -> dict[str, Any]:
    return {
        "enable_adjust": True,
        "enable_color_correct_adjust": False,
        "enable_color_curves": True,
        "enable_color_match_adjust": False,
        "enable_color_wheels": True,
        "enable_lut": True,
        "enable_smart_color_adjust": False,
        "last_nonzero_volume": 1.0,
        "reverse": False,
        "track_attribute": 0,
        "track_render_index": 0,
        "visible": True,
        "id": uuid.uuid4().hex,
        "material_id": material_id,
        "target_timerange": {"start": int(start), "duration": int(duration)},
        "common_keyframes": [],
        "keyframe_refs": [],
    }


def _track(track_type: str, name: str, render_index: int, segments: list[dict[str, Any]]) -> dict[str, Any]:
    for segment in segments:
        segment["render_index"] = render_index
    return {"attribute": 0, "flag": 0, "id": uuid.uuid4().hex, "is_default_name": False, "name": name, "segments": segments, "type": track_type}


def _video_material(path: str, duration_us: int, width: int, height: int) -> dict[str, Any]:
    material_id = uuid.uuid4().hex
    return {
        "audio_fade": None,
        "category_id": "",
        "category_name": "local",
        "check_flag": 63487,
        "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0, "lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0},
        "crop_ratio": "free",
        "crop_scale": 1.0,
        "duration": int(duration_us),
        "height": int(height),
        "id": material_id,
        "local_material_id": "",
        "material_id": material_id,
        "material_name": Path(path).name,
        "media_path": "",
        "path": path,
        "type": "video",
        "width": int(width),
    }


def _audio_material(path: str, duration_us: int) -> dict[str, Any]:
    material_id = uuid.uuid4().hex
    return {"app_id": 0, "category_id": "", "category_name": "local", "check_flag": 3, "copyright_limit_type": "none", "duration": int(duration_us), "effect_id": "", "formula_id": "", "id": material_id, "local_material_id": material_id, "music_id": material_id, "name": Path(path).name, "path": path, "source_platform": 0, "type": "extract_music", "wave_points": []}


def _speed_material(speed_id: str, speed: float) -> dict[str, Any]:
    return {"curve_speed": None, "id": speed_id, "mode": 0, "speed": speed, "type": "speed"}


def _text_material(material_id: str, text: str) -> dict[str, Any]:
    content = {
        "styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [1.0, 1.0, 1.0]}}}, "range": [0, len(text)], "size": 8.0, "bold": False, "italic": False, "underline": False, "strokes": [{"content": {"solid": {"alpha": 1.0, "color": [0.0, 0.0, 0.0]}}, "width": 0.072}]}],
        "text": text,
    }
    return {"id": material_id, "content": json.dumps(content, ensure_ascii=False), "typesetting": 0, "alignment": 1, "letter_spacing": 0.0, "line_spacing": 0.02, "line_feed": 1, "line_max_width": 0.86, "force_apply_line_max_width": False, "check_flag": 15, "type": "subtitle", "global_alpha": 1.0}


def _clip(transform_y: float = 0.0) -> dict[str, Any]:
    return {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0, "scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": transform_y}}
