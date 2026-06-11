from __future__ import annotations

from pathlib import Path

from packages.media.video.ffmpeg import FfmpegRunner, ffmpeg_bin


def estimate_sandbox_tts_duration(text: str, *, speed: float = 1.0) -> float:
    char_count = len([char for char in text if not char.isspace()])
    chars_per_second = max(0.1, 4.5 * speed)
    return max(1.0, round(char_count / chars_per_second, 3))


def synthesize_sandbox_tts(
    text: str,
    output_path: Path,
    *,
    speed: float = 1.0,
    volume: float = 1.0,
) -> float:
    duration = estimate_sandbox_tts_duration(text, speed=speed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
            f"sine=frequency=440:sample_rate=16000:duration={duration:.3f}",
            "-af",
            f"volume={min(max(volume, 0.0), 2.0) * 0.18:.3f}",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )
    return duration
