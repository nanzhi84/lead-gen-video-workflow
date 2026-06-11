from __future__ import annotations

import hashlib

from packages.core.contracts import MediaInfo
from packages.media.video.ffmpeg import (
    extract_thumbnails,
    probe_media,
    sha256_file,
)
from tests.fixtures.media import generate_test_audio, generate_test_video


def test_probe_media_reads_real_video_stream_info(tmp_path):
    video = generate_test_video(tmp_path, duration_sec=2, width=320, height=568, fps=30)

    info = probe_media(video)

    assert isinstance(info, MediaInfo)
    assert info.media_type == "video"
    assert info.format
    assert info.codec
    assert info.width == 320
    assert info.height == 568
    assert info.fps == 30
    assert 1.9 <= (info.duration_sec or 0) <= 2.2
    assert sha256_file(video) == hashlib.sha256(video.read_bytes()).hexdigest()


def test_probe_media_reads_real_audio_stream_info(tmp_path):
    audio = generate_test_audio(tmp_path, duration_sec=1.5, sample_rate=16000)

    info = probe_media(audio)

    assert info.media_type == "audio"
    assert info.codec
    assert info.format
    assert info.sample_rate == 16000
    assert info.channels == 1
    assert 1.4 <= (info.duration_sec or 0) <= 1.7


def test_extract_thumbnails_writes_first_and_midpoint_pngs(tmp_path):
    video = generate_test_video(tmp_path, duration_sec=2, width=320, height=568, fps=30)
    output_dir = tmp_path / "thumbs"

    thumbs = extract_thumbnails(video, output_dir, labels=("first", "mid"))

    assert [thumb.label for thumb in thumbs] == ["first", "mid"]
    assert all(thumb.path.exists() for thumb in thumbs)
    assert all(thumb.sha256 == sha256_file(thumb.path) for thumb in thumbs)
    assert all(thumb.media_info.media_type == "image" for thumb in thumbs)
    assert all(thumb.media_info.width == 320 for thumb in thumbs)
    assert all(thumb.media_info.height == 568 for thumb in thumbs)


def test_session_media_fixture_factory_caches_generated_assets(media_fixture_factory):
    first = media_fixture_factory.video(duration_sec=1, width=320, height=568, fps=30)
    second = media_fixture_factory.video(duration_sec=1, width=320, height=568, fps=30)
    audio = media_fixture_factory.audio(duration_sec=1, sample_rate=16000)

    assert first == second
    assert first.exists()
    assert audio.exists()
