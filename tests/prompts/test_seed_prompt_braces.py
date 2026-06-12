from __future__ import annotations

from string import Formatter

from packages.core.storage.repository import Repository


def _format_fields(content: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in Formatter().parse(content)
        if field_name is not None
    }


def test_production_seed_prompts_only_use_declared_format_variables():
    repository = Repository()
    cases = {
        "prompt_creative_intent_v1": {"script": "示例脚本"},
        "prompt_case_agent_script_v1": {"brief": "示例 brief", "memories": "示例记忆"},
        "prompt_vlm_annotation_v1": {"asset_id": "asset_1", "asset_kind": "video"},
    }

    for version_id, variables in cases.items():
        content = repository.prompt_versions[version_id].content
        assert _format_fields(content) == set(variables)
        content.format(**variables)


def test_creative_intent_seed_prompt_requests_top_level_contract():
    content = Repository().prompt_versions["prompt_creative_intent_v1"].content

    assert content.count("{script}") == 1
    assert "hook" in content
    assert "tone" in content
    assert "audience" in content
    assert "beats" in content
    assert "禁止使用 markdown 代码块" in content
    assert "不要再嵌套 intent" not in content
