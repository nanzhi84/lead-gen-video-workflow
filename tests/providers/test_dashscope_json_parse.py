from __future__ import annotations

from packages.ai.providers.dashscope import _parse_json_object


def test_parse_json_object_accepts_markdown_json_fence():
    content = '```json\n{"ok": true, "items": [1, 2]}\n```'

    assert _parse_json_object(content) == {"ok": True, "items": [1, 2]}
