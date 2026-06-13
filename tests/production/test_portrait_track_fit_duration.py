"""Regression tests for the portrait-track fit-to-exact-duration fix.

PortraitTrackBuild used to fail for longer audio: per-segment ``-t`` ms
quantization + fps resampling + ``concat -c copy`` accumulate sub-frame drift
that exceeds the old ``1/fps`` tolerance once the track is long enough (it
passed at <=~10.6s and failed at >=~11.19s, independent of the render args).

The fix forces the concatenated track to be EXACTLY the plan duration via an
extra ffmpeg pass (clone-pad if short, trim if long), then relaxes the sanity
check tolerance to ``max(2/fps, 0.05)`` so it only fires on a gross render
failure rather than on ms quantization.

These tests mock the ffmpeg layer (no real TTS media exists here) to assert:
(a) the fit-to-duration step is invoked with the plan duration as target;
(b) the relaxed check tolerates small quantization but rejects a grossly-wrong
    duration.
A separate test drives the real ``fit_video_to_exact_duration`` ffmpeg pass to
prove it pads-short and trims-long to the exact target.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest import mock

import pytest

from packages.core.contracts import ErrorCode, MediaInfo
from packages.core.workflow import NodeExecutionError
from packages.media.video.ffmpeg import ffmpeg_bin, probe_media
from packages.production.pipeline import digital_human as dh
from packages.production.pipeline import render_ops

PLAN_FPS = 30
PLAN_WIDTH = 320
PLAN_HEIGHT = 568
# The historically-failing duration: drift exceeded 1/fps here.
PLAN_DURATION = 11.19


def _media_info(duration: float) -> MediaInfo:
    return MediaInfo(
        media_type="video",
        codec="h264",
        format="mp4",
        duration_sec=duration,
        width=PLAN_WIDTH,
        height=PLAN_HEIGHT,
        fps=float(PLAN_FPS),
    )


def _adapter_for_portrait(probe_duration: float, fit_spy: mock.Mock):
    """Build a bare adapter with all ffmpeg/IO seams stubbed for the test.

    ``__new__`` bypasses the expensive seed-media bootstrap; we only need the
    ``_portrait_track_build`` control flow.
    """
    adapter = dh.LocalRuntimeAdapter.__new__(dh.LocalRuntimeAdapter)

    # Resolve segment sources to a sentinel path; source-window validation reads
    # source_info.duration_sec, so give the source a large duration.
    source_artifact = mock.Mock()
    source_artifact.media_info = _media_info(60.0)
    adapter._source_artifact_for_asset = mock.Mock(return_value=source_artifact)  # type: ignore[method-assign]
    adapter._artifact_path = mock.Mock(return_value=Path("source.mp4"))  # type: ignore[method-assign]
    adapter._transcode_video_segment = mock.Mock()  # type: ignore[method-assign]
    adapter._concat_video_segments = mock.Mock()  # type: ignore[method-assign]
    adapter._fit_video_to_exact_duration = fit_spy  # type: ignore[method-assign]
    adapter._artifact = mock.Mock(return_value=mock.Mock())  # type: ignore[method-assign]
    return adapter


def _run_portrait_build(adapter, probe_duration: float):
    portrait_artifact = mock.Mock()
    portrait_artifact.payload = {
        "duration_sec": PLAN_DURATION,
        "fps": PLAN_FPS,
        "segments": [
            {"asset_id": "asset_a", "source_start": 0.0, "source_end": 6.0, "end_sec": 6.0},
            {"asset_id": "asset_a", "source_start": 6.0, "source_end": PLAN_DURATION, "end_sec": PLAN_DURATION},
        ],
    }
    state = mock.Mock()
    state.require.return_value = portrait_artifact
    state.request.output.fps = PLAN_FPS
    state.request.output.width = PLAN_WIDTH
    state.request.output.height = PLAN_HEIGHT

    with (
        mock.patch.object(dh, "probe_media", return_value=_media_info(probe_duration)),
        mock.patch.object(dh, "store_file") as store_file,
        mock.patch.object(dh, "get_object_store"),
        mock.patch.object(dh, "NodeOutput", side_effect=lambda **kw: kw),
    ):
        store_file.return_value = mock.Mock(ref=mock.Mock(uri="object://portrait.mp4"), sha256="deadbeef")
        return adapter._portrait_track_build(mock.Mock(), mock.Mock(), state)


def test_fit_to_duration_invoked_with_plan_duration():
    """(a) The fit step runs with the plan total duration as the target."""
    fit_spy = mock.Mock()
    adapter = _adapter_for_portrait(PLAN_DURATION, fit_spy)
    # probe returns slightly-off (ms quantization) but within the relaxed band.
    _run_portrait_build(adapter, probe_duration=PLAN_DURATION + 0.02)

    fit_spy.assert_called_once()
    kwargs = fit_spy.call_args.kwargs
    assert kwargs["duration"] == pytest.approx(PLAN_DURATION)
    assert kwargs["fps"] == PLAN_FPS
    assert kwargs["width"] == PLAN_WIDTH
    assert kwargs["height"] == PLAN_HEIGHT
    # Concat happens first into a raw path; fit reads that, writes the final path.
    raw_src, final_out = fit_spy.call_args.args
    assert raw_src != final_out


def test_relaxed_check_tolerates_small_quantization():
    """(b1) A few-ms drift after the fit pass must NOT raise."""
    fit_spy = mock.Mock()
    adapter = _adapter_for_portrait(PLAN_DURATION, fit_spy)
    # Within max(2/fps, 0.05) ~= 0.0667s, but beyond the old 1/fps ~= 0.0333s.
    drifted = PLAN_DURATION + 0.05
    assert abs(drifted - PLAN_DURATION) > (1 / PLAN_FPS)  # old check would have failed
    # Should not raise.
    _run_portrait_build(adapter, probe_duration=drifted)


def test_relaxed_check_rejects_gross_mismatch():
    """(b2) A grossly-wrong duration still raises render_invalid_timeline."""
    fit_spy = mock.Mock()
    adapter = _adapter_for_portrait(PLAN_DURATION, fit_spy)
    with pytest.raises(NodeExecutionError) as exc:
        _run_portrait_build(adapter, probe_duration=PLAN_DURATION + 2.0)
    assert exc.value.error.code == ErrorCode.render_invalid_timeline


@pytest.mark.skipif(shutil.which(ffmpeg_bin()) is None, reason="ffmpeg not available")
@pytest.mark.parametrize("source_dur,target", [(2.0, 5.0), (8.0, 5.0)])
def test_fit_video_to_exact_duration_real_ffmpeg(tmp_path: Path, source_dur: float, target: float):
    """The real ffmpeg pass pads-short / trims-long to the exact target.

    Covers both branches: a 2s source padded up to 5s (clone) and an 8s source
    trimmed down to 5s. The output must be >= target (no end freeze for the
    already-long case) and not materially longer.
    """
    from packages.media.video.ffmpeg import FfmpegRunner

    src = tmp_path / f"src_{source_dur:g}.mp4"
    FfmpegRunner().run(
        [
            ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc2=size={PLAN_WIDTH}x{PLAN_HEIGHT}:rate={PLAN_FPS}",
            "-t", f"{source_dur:.3f}", "-pix_fmt", "yuv420p", "-c:v", "libx264",
            "-preset", "ultrafast", str(src),
        ]
    )
    out = tmp_path / "fitted.mp4"
    render_ops.fit_video_to_exact_duration(
        src, out, duration=target, width=PLAN_WIDTH, height=PLAN_HEIGHT, fps=PLAN_FPS,
    )
    info = probe_media(out)
    actual = float(info.duration_sec or 0)
    # Exactly target within a couple frames; never short, never materially long.
    assert actual >= target - (1 / PLAN_FPS)
    assert abs(actual - target) <= max(2 / PLAN_FPS, 0.05)
