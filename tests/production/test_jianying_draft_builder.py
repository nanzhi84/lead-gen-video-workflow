from __future__ import annotations

import json
import zipfile

from packages.core.storage.object_store import LocalObjectStore, parse_object_uri
from packages.production.jianying_draft import JianyingDraftBuilder, JianyingDraftInput


def test_jianying_builder_writes_real_draft_zip_with_tracks_and_microseconds(tmp_path, media_fixture_factory):
    video = media_fixture_factory.video(duration_sec=2, width=320, height=568, filename="portrait.mp4")
    audio = media_fixture_factory.audio(duration_sec=2, filename="voice.wav")
    subtitle = tmp_path / "narration.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n第一句\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\n第二句\n",
        encoding="utf-8",
    )
    narration_units = [
        {"unit_id": "n1", "start": 0.0, "end": 1.0, "text": "第一句"},
        {"unit_id": "n2", "start": 1.0, "end": 2.0, "text": "第二句"},
    ]
    timeline_plan = {
        "fps": 30,
        "total_frames": 60,
        "tracks": [
            {
                "track_id": "portrait",
                "segment_id": "portrait_1",
                "timeline_start_frame": 0,
                "timeline_end_frame": 30,
                "source_start_frame": 0,
                "source_end_frame": 30,
                "asset_path": str(video),
            },
            {
                "track_id": "portrait",
                "segment_id": "portrait_2",
                "timeline_start_frame": 30,
                "timeline_end_frame": 60,
                "source_start_frame": 30,
                "source_end_frame": 60,
                "asset_path": str(video),
            },
        ],
    }

    object_store = LocalObjectStore(tmp_path / "objects")
    result = JianyingDraftBuilder(object_store).build(
        JianyingDraftInput(
            finished_video_id="fv_test",
            title="测试剪映草稿",
            video_path=video,
            audio_path=audio,
            subtitle_path=subtitle,
            duration_sec=2.0,
            template_id="clean-template",
            timeline_plan=timeline_plan,
            narration_units=narration_units,
        )
    )

    assert result.package_uri.startswith("local://")
    assert result.draft_name
    assert result.tracks_summary == {
        "main_video": 2,
        "voice_audio": 1,
        "subtitle_segments": 2,
        "broll_segments": 0,
        "overlay_tracks": 0,
        "cover_tracks": 0,
        "huazi_segments": 0,
    }

    package_path = object_store._path(parse_object_uri(result.package_uri))
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        draft_prefix = f"{result.draft_name}/"
        assert "root_meta_info.json" in names
        assert f"{draft_prefix}draft_content.json" in names
        assert f"{draft_prefix}draft_meta_info.json" in names
        assert any(name.startswith(f"{draft_prefix}Resources/video/") and name.endswith(".mp4") for name in names)
        assert any(name.startswith(f"{draft_prefix}Resources/audio/") and name.endswith(".wav") for name in names)

        content = json.loads(archive.read(f"{draft_prefix}draft_content.json").decode("utf-8"))
        meta = json.loads(archive.read(f"{draft_prefix}draft_meta_info.json").decode("utf-8"))

    assert content["duration"] == 2_000_000
    assert content["canvas_config"]["width"] == 320
    assert content["canvas_config"]["height"] == 568
    assert meta["tm_duration"] == 2_000_000
    assert meta["draft_timeline_materials_size_"] > 0

    tracks = {track["name"]: track for track in content["tracks"]}
    assert tracks["video"]["type"] == "video"
    assert tracks["audio"]["type"] == "audio"
    assert tracks["subtitle"]["type"] == "text"
    video_ranges = [segment["target_timerange"] for segment in tracks["video"]["segments"]]
    assert video_ranges == [
        {"start": 0, "duration": 1_000_000},
        {"start": 1_000_000, "duration": 1_000_000},
    ]
    assert all(isinstance(value, int) for item in video_ranges for value in item.values())
    assert tracks["audio"]["segments"][0]["target_timerange"] == {"start": 0, "duration": 2_000_000}
    assert len(tracks["subtitle"]["segments"]) == len(narration_units)
    assert [segment["target_timerange"]["start"] for segment in tracks["subtitle"]["segments"]] == [0, 1_000_000]

    subtitle_texts = [
        json.loads(material["content"])["text"]
        for material in content["materials"]["texts"]
    ]
    assert subtitle_texts == ["第一句", "第二句"]
