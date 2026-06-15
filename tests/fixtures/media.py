from __future__ import annotations

from pathlib import Path

from packages.media.video.ffmpeg import FfmpegRunner, ffmpeg_bin


class MediaFixtureFactory:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def video(
        self,
        *,
        duration_sec: float = 2,
        width: int = 320,
        height: int = 568,
        fps: int = 30,
        filename: str | None = None,
    ) -> Path:
        return generate_test_video(
            self.directory,
            duration_sec=duration_sec,
            width=width,
            height=height,
            fps=fps,
            filename=filename,
        )

    def audio(
        self,
        *,
        duration_sec: float = 2,
        sample_rate: int = 16000,
        frequency: int = 440,
        filename: str | None = None,
    ) -> Path:
        return generate_test_audio(
            self.directory,
            duration_sec=duration_sec,
            sample_rate=sample_rate,
            frequency=frequency,
            filename=filename,
        )


def generate_test_video(
    directory: Path,
    *,
    duration_sec: float = 2,
    width: int = 320,
    height: int = 568,
    fps: int = 30,
    filename: str | None = None,
) -> Path:
    path = directory / (filename or f"testsrc2_{width}x{height}_{fps}fps_{duration_sec:g}s.mp4")
    if path.exists():
        return path
    FfmpegRunner().run(
        [
            ffmpeg_bin(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x{height}:rate={fps}",
            "-t",
            f"{duration_sec:.3f}",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-movflags",
            "+faststart",
            str(path),
        ]
    )
    return path


def generate_test_hdr_video(
    directory: Path,
    *,
    duration_sec: float = 1,
    width: int = 320,
    height: int = 568,
    fps: int = 15,
    filename: str | None = None,
) -> Path:
    """Generate a BT.2020 / PQ (smpte2084) HDR video for tonemap tests.

    Uses HEVC 10-bit with explicit HDR color tags so ``probe_media`` reports
    ``is_hdr=True``."""
    path = directory / (filename or f"hdr_{width}x{height}_{fps}fps_{duration_sec:g}s.mp4")
    if path.exists():
        return path
    FfmpegRunner().run(
        [
            ffmpeg_bin(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x{height}:rate={fps}",
            "-t",
            f"{duration_sec:.3f}",
            "-pix_fmt",
            "yuv420p10le",
            "-c:v",
            "libx265",
            "-x265-params",
            "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc",
            "-color_primaries",
            "bt2020",
            "-color_trc",
            "smpte2084",
            "-colorspace",
            "bt2020nc",
            str(path),
        ]
    )
    return path


def generate_test_audio(
    directory: Path,
    *,
    duration_sec: float = 2,
    sample_rate: int = 16000,
    frequency: int = 440,
    filename: str | None = None,
) -> Path:
    path = directory / (filename or f"sine_{sample_rate}hz_{duration_sec:g}s.wav")
    if path.exists():
        return path
    FfmpegRunner().run(
        [
            ffmpeg_bin(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate={sample_rate}:duration={duration_sec:.3f}",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(path),
        ]
    )
    return path
