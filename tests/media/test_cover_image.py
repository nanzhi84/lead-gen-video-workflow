from __future__ import annotations

from packages.media.cover import CoverPromptInputs, SEEDREAM_COVER_REQUEST_SIZE, build_cover_prompt
from packages.media.cover_image import (
    COVER_TARGET_HEIGHT,
    COVER_TARGET_WIDTH,
    normalize_cover_image_bytes,
)
from packages.media.video.ffmpeg import probe_media


_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f"
    "15c4890000000b49444154789c6360000200000500017a5eab3f00000000"
    "49454e44ae426082"
)


def test_normalize_cover_image_bytes_outputs_9_16_png(tmp_path):
    cover_path = tmp_path / "cover.png"
    cover_path.write_bytes(normalize_cover_image_bytes(_PNG_1x1))

    info = probe_media(cover_path)

    assert info.media_type == "image"
    assert info.width == COVER_TARGET_WIDTH
    assert info.height == COVER_TARGET_HEIGHT


def test_default_cover_prompt_targets_9_16():
    prompt = build_cover_prompt(CoverPromptInputs(title="轮毂修复省两千", description="案例摘要"))

    assert "1080x1920" in prompt
    assert "9:16" in prompt
    assert "3:4" not in prompt
    assert "生成一张" in prompt
    assert "不是普通截图贴字" in prompt
    assert "由模型自主设计" in prompt
    assert "Main headline" not in prompt
    assert "selected video frame" not in prompt


def test_seedream_cover_request_size_meets_custom_pixel_floor():
    width, height = [int(part) for part in SEEDREAM_COVER_REQUEST_SIZE.split("x")]

    assert width / height == 9 / 16
    assert width * height >= 3_686_400
