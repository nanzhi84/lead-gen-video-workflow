from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from packages.core.contracts import PromptSchemaRef, PromptTemplate, PromptVersion, utcnow


@dataclass(frozen=True)
class PromptGroupSeed:
    template_id: str
    version_id: str
    name: str
    purpose: str
    source_key: str
    variables_schema_id: str
    output_schema_id: str
    variable_hints: tuple[str, ...]
    content: str


LEGACY_PROMPT_VARIABLE_HINTS: dict[str, tuple[str, ...]] = {
    "prompt_creative_intent": ("script",),
    "prompt_case_agent_script": ("brief", "memories"),
    "prompt_vlm_annotation": ("asset_id", "asset_kind"),
}


def prompt_group_seeds() -> tuple[PromptGroupSeed, ...]:
    return _load_prompt_group_seeds()


def prompt_variable_hints(template_id: str) -> list[str]:
    hints = _prompt_variable_hints_by_id().get(template_id)
    return list(hints or ())


def seed_prompt_groups(repository: Any) -> None:
    for seed in prompt_group_seeds():
        if seed.template_id in repository.prompt_templates:
            continue
        now = utcnow()
        template = PromptTemplate(
            id=seed.template_id,
            name=seed.name,
            purpose=seed.purpose,
            variables_schema_ref=PromptSchemaRef(schema_id=seed.variables_schema_id),
            output_schema_ref=PromptSchemaRef(schema_id=seed.output_schema_id),
            status="active",
        )
        version = PromptVersion(
            id=seed.version_id,
            prompt_template_id=seed.template_id,
            content=seed.content,
            status="published",
            approved_at=now,
            published_at=now,
        )
        repository.prompt_templates[template.id] = template
        repository.prompt_versions[version.id] = version


@lru_cache(maxsize=1)
def _load_prompt_group_seeds() -> tuple[PromptGroupSeed, ...]:
    path = Path(__file__).with_name("prompt_group_defaults.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        PromptGroupSeed(
            template_id=item["template_id"],
            version_id=item["version_id"],
            name=item["name"],
            purpose=item["purpose"],
            source_key=item["source_key"],
            variables_schema_id=item["variables_schema_id"],
            output_schema_id=item["output_schema_id"],
            variable_hints=tuple(item["variable_hints"]),
            content=item["content"],
        )
        for item in payload["items"]
    )


@lru_cache(maxsize=1)
def _prompt_variable_hints_by_id() -> dict[str, tuple[str, ...]]:
    hints = {seed.template_id: seed.variable_hints for seed in prompt_group_seeds()}
    hints.update(LEGACY_PROMPT_VARIABLE_HINTS)
    return hints
