from __future__ import annotations

import inspect
import re
from pathlib import Path

from packages.core.contracts import Artifact, ArtifactKind, MediaInfo
from packages.media.rendering import render_video_timeline, transcode_video_segment
import packages.media.rendering.timeline as rendering_timeline
from packages.production.pipeline._timeline_grid import to_frame


def _video_artifact(asset_id: str, path: Path, *, duration_sec: float = 3.0) -> Artifact:
    return Artifact(
        id=f"art_{asset_id}",
        kind=ArtifactKind.uploaded_file,
        local_path=str(path),
        media_info=MediaInfo(
            media_type="video",
            codec="h264",
            format="mp4",
            width=320,
            height=180,
            fps=30.0,
            duration_sec=duration_sec,
        ),
        payload_schema="UploadedFileArtifact.v1",
        payload=None,
    )


def test_render_video_timeline_uses_frame_boundaries_for_broll_overlay(monkeypatch, tmp_path):
    captured: dict[str, list[str]] = {}

    def capture_run(self, args):
        captured["args"] = args

    monkeypatch.setattr(rendering_timeline.FfmpegRunner, "run", capture_run)
    artifact = _video_artifact("asset_a", tmp_path / "asset_a.mp4")

    render_video_timeline(
        main_path=tmp_path / "main.mp4",
        output_path=tmp_path / "rendered.mp4",
        broll_segments=[
            {
                "asset_id": "asset_a",
                "source_start": 0.033,
                "source_end": 1.067,
                "source_start_frame": 1,
                "source_end_frame": 32,
                "start_sec": 0.067,
                "end_sec": 1.067,
                "timeline_start_frame": 2,
                "timeline_end_frame": 32,
            }
        ],
        total_frames=90,
        width=160,
        height=90,
        fps=30,
        source_artifact_for_asset=lambda _asset_id: artifact,
        artifact_path=lambda source_artifact: Path(source_artifact.local_path),
    )

    args = captured["args"]
    filter_complex = args[args.index("-filter_complex") + 1]

    assert "trim=start_frame=1:end_frame=32" in filter_complex
    assert "enable='gte(n\\,2)*lt(n\\,32)'" in filter_complex
    assert "between(t," not in filter_complex
    assert re.search(r"trim=start=\d+(?:\.\d+)?", filter_complex) is None


def test_transcode_video_segment_uses_output_frame_trim_without_input_seek(monkeypatch, tmp_path):
    signature = inspect.signature(transcode_video_segment)
    assert "source_start_frame" in signature.parameters
    assert "source_end_frame" in signature.parameters
    assert "source_start" not in signature.parameters
    assert "duration" not in signature.parameters

    captured: dict[str, list[str]] = {}

    def capture_run(self, args):
        captured["args"] = args

    monkeypatch.setattr(rendering_timeline.FfmpegRunner, "run", capture_run)

    transcode_video_segment(
        tmp_path / "source.mp4",
        tmp_path / "segment.mp4",
        source_start_frame=3,
        source_end_frame=27,
        width=160,
        height=90,
        fps=30,
    )

    args = captured["args"]
    input_index = args.index("-i")
    assert "-ss" not in args[:input_index]
    assert "-t" not in args[:input_index]
    vf = args[args.index("-vf") + 1]
    assert "fps=30,trim=start_frame=3:end_frame=27" in vf
    assert "trim=start=" not in vf


def test_to_frame_rounds_half_frames_up():
    assert to_frame(12.5 / 30, 30) == 13
