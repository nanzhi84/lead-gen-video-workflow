from __future__ import annotations

from pathlib import Path

from packages.core.contracts import Artifact, ArtifactKind
from packages.media.rendering import render_broll_montage, validate_rendered_output
from packages.media.video.ffmpeg import probe_stream_types


def _artifact(asset_id: str, path: Path) -> Artifact:
    return Artifact(
        id=f"art_{asset_id}",
        kind=ArtifactKind.uploaded_file,
        local_path=str(path),
        payload_schema="UploadedFileArtifact.v1",
        payload=None,
    )


def test_render_broll_montage_outputs_exact_frame_count_and_shape(
    tmp_path,
    media_fixture_factory,
):
    source_a = media_fixture_factory.video(
        duration_sec=2.0,
        width=320,
        height=180,
        fps=24,
        filename="broll_montage_a.mp4",
    )
    source_b = media_fixture_factory.video(
        duration_sec=2.5,
        width=180,
        height=320,
        fps=24,
        filename="broll_montage_b.mp4",
    )
    artifacts = {
        "asset_a": _artifact("asset_a", source_a),
        "asset_b": _artifact("asset_b", source_b),
    }
    output_path = tmp_path / "montage.mp4"
    total_frames = 72

    render_broll_montage(
        segments=[
            {
                "asset_id": "asset_a",
                "source_start": 0.0,
                "source_end": 1.25,
                "timeline_start": 0.0,
                "timeline_end": 1.25,
            },
            {
                "asset_id": "asset_b",
                "source_start": 0.25,
                "source_end": 2.0,
                "timeline_start": 1.25,
                "timeline_end": 3.0,
            },
        ],
        output_path=output_path,
        total_frames=total_frames,
        width=160,
        height=90,
        fps=24,
        source_artifact_for_asset=lambda asset_id: artifacts[asset_id],
        artifact_path=lambda artifact: Path(artifact.local_path),
    )

    validate_rendered_output(
        output_path,
        expected_frames=total_frames,
        expected_width=160,
        expected_height=90,
        expected_fps=24,
    )
    assert probe_stream_types(output_path) == {"video"}
