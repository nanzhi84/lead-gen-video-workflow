from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Sequence

from packages.core.contracts import ErrorCode, MediaInfo


DEFAULT_TIMEOUT_SEC = 30


class FfmpegCommandError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: ErrorCode = ErrorCode.render_failed,
        command: Sequence[str] | None = None,
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.command = list(command or [])
        self.stderr = stderr


@dataclass(frozen=True)
class ThumbnailResult:
    label: str
    path: Path
    sha256: str
    media_info: MediaInfo


def ffmpeg_bin() -> str:
    return _resolve_bin("CUTAGENT_FFMPEG_BIN", "ffmpeg")


def ffprobe_bin() -> str:
    return _resolve_bin("CUTAGENT_FFPROBE_BIN", "ffprobe")


def _resolve_bin(env_name: str, executable: str) -> str:
    configured = os.getenv(env_name)
    if configured:
        return configured
    found = shutil.which(executable)
    if found:
        return found
    local = Path.home() / ".local" / "bin" / executable
    if local.exists():
        return str(local)
    return executable


class FfmpegRunner:
    def __init__(self, *, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> None:
        self.timeout_sec = timeout_sec

    def run(self, args: Sequence[str], *, timeout_sec: int | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                list(args),
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_sec or self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise FfmpegCommandError(
                f"Media command timed out after {timeout_sec or self.timeout_sec}s.",
                error_code=ErrorCode.provider_timeout,
                command=args,
                stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr or ""
            raise FfmpegCommandError(
                f"Media command failed with exit code {exc.returncode}.",
                error_code=ErrorCode.render_failed,
                command=args,
                stderr=stderr,
            ) from exc


def probe_media(path: str | Path) -> MediaInfo:
    media_path = Path(path)
    if not media_path.exists():
        raise FfmpegCommandError(
            f"Media file does not exist: {media_path}",
            error_code=ErrorCode.artifact_missing,
        )
    result = FfmpegRunner().run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-show_entries",
            (
                "format=format_name,duration:stream="
                "codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels,duration"
            ),
            "-of",
            "json",
            str(media_path),
        ]
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FfmpegCommandError("ffprobe returned invalid JSON.", command=[ffprobe_bin(), str(media_path)]) from exc
    streams = payload.get("streams") or []
    format_info = payload.get("format") or {}
    if not streams:
        raise FfmpegCommandError(f"No media streams found in {media_path}.")
    primary = _primary_stream(streams)
    codec_type = str(primary.get("codec_type") or "")
    codec = str(primary.get("codec_name") or "unknown")
    fmt = str(format_info.get("format_name") or media_path.suffix.lstrip(".") or "unknown")
    duration = _float_or_none(format_info.get("duration")) or _float_or_none(primary.get("duration"))
    if codec_type == "subtitle":
        return MediaInfo(
            media_type="subtitle",
            codec=codec,
            format=fmt,
            duration_sec=duration,
        )
    if codec_type == "audio":
        return MediaInfo(
            media_type="audio",
            codec=codec,
            format=fmt,
            duration_sec=duration,
            sample_rate=_int_or_none(primary.get("sample_rate")),
            channels=_int_or_none(primary.get("channels")),
        )
    media_type = "image" if _is_image(media_path, fmt, duration) else "video"
    return MediaInfo(
        media_type=media_type,
        codec=codec,
        format=fmt,
        duration_sec=None if media_type == "image" else duration,
        width=_int_or_none(primary.get("width")),
        height=_int_or_none(primary.get("height")),
        fps=None if media_type == "image" else _fps(primary),
    )


def extract_thumbnails(
    video_path: str | Path,
    output_dir: str | Path,
    *,
    labels: tuple[str, str] = ("first", "mid"),
) -> list[ThumbnailResult]:
    source = Path(video_path)
    info = probe_media(source)
    if info.media_type != "video":
        raise FfmpegCommandError(f"Thumbnail source must be video: {source}")
    duration = float(info.duration_sec or 0)
    timestamps = [0.0, max(0.0, duration / 2.0)]
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[ThumbnailResult] = []
    for label, timestamp in zip(labels, timestamps, strict=True):
        output = out_dir / f"{label}.png"
        FfmpegRunner().run(
            [
                ffmpeg_bin(),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-update",
                "1",
                str(output),
            ]
        )
        results.append(
            ThumbnailResult(
                label=label,
                path=output,
                sha256=sha256_file(output),
                media_info=probe_media(output),
            )
        )
    return results


def probe_video_frame_count(path: str | Path) -> int:
    media_path = Path(path)
    result = FfmpegRunner().run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames,nb_frames",
            "-of",
            "json",
            str(media_path),
        ]
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FfmpegCommandError("ffprobe returned invalid JSON.", command=[ffprobe_bin(), str(media_path)]) from exc
    streams = payload.get("streams") or []
    if not streams:
        raise FfmpegCommandError(f"No video stream found in {media_path}.")
    stream = streams[0]
    frame_count = _int_or_none(stream.get("nb_read_frames")) or _int_or_none(stream.get("nb_frames"))
    if frame_count is None:
        raise FfmpegCommandError(f"Could not count frames in {media_path}.")
    return frame_count


def probe_stream_types(path: str | Path) -> set[str]:
    media_path = Path(path)
    result = FfmpegRunner().run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(media_path),
        ]
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FfmpegCommandError("ffprobe returned invalid JSON.", command=[ffprobe_bin(), str(media_path)]) from exc
    return {str(stream.get("codec_type")) for stream in payload.get("streams") or [] if stream.get("codec_type")}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _primary_stream(streams: list[dict]) -> dict:
    for stream in streams:
        if stream.get("codec_type") == "video":
            return stream
    for stream in streams:
        if stream.get("codec_type") == "audio":
            return stream
    return streams[0]


def _fps(stream: dict) -> float | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = stream.get(key)
        if value and value != "0/0":
            parsed = float(Fraction(str(value)))
            if parsed > 0:
                return parsed
    return None


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_image(path: Path, fmt: str, duration: float | None) -> bool:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return True
    image_formats = {"image2", "png_pipe", "jpeg_pipe", "webp_pipe"}
    return fmt in image_formats and duration in {None, 0}
