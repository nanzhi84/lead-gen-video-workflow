from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from packages.core.contracts import ErrorCode, PromptBinding, PromptInvocation, PromptTemplate, PromptVersion
from packages.core.storage import Repository
from packages.core.storage.repository import new_id
from packages.core.workflow import NodeExecutionError


def case_prompt_variables(case: Any) -> dict[str, str]:
    """Bridge a Case contract object to the prompt-template variable vocabulary.

    The Case contract keeps its own field names (name, product, strategy_tags, ...),
    while the prompt templates in prompt_group_defaults.json reference a different
    vocabulary ({case_name}{product_name}{industry}{target_audience}{ip_persona}
    {brand_voice}{key_selling_points}{description}{tags}). This helper maps between
    them so #B wiring fills the templates with real Case values instead of leaving
    them permanently empty.

    List fields are serialized as ", ".join(...) so registry.render's str()-based
    token replacement does not emit a Python list repr. brand_keywords and
    competitor_names are intentionally NOT mapped: no template var references them
    today (they are stored/returned but not yet wired into render).
    """

    def _text(value: Any) -> str:
        return "" if value is None else str(value)

    def _joined(value: Any) -> str:
        if not value:
            return ""
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        return str(value)

    return {
        "case_name": _text(getattr(case, "name", None)),
        "product_name": _text(getattr(case, "product", None)),
        "industry": _text(getattr(case, "industry", None)),
        "target_audience": _text(getattr(case, "target_audience", None)),
        "ip_persona": _text(getattr(case, "ip_persona", None)),
        "brand_voice": _text(getattr(case, "brand_voice", None)),
        "key_selling_points": _joined(getattr(case, "key_selling_points", None)),
        "description": _text(getattr(case, "description", None)),
        "tags": _joined(getattr(case, "strategy_tags", None)),
    }


class PromptRuntimeReader(Protocol):
    def resolve_published_version(
        self,
        *,
        node_id: str,
        case_id: str | None = None,
        provider_profile_id: str | None = None,
    ) -> tuple[PromptBinding, PromptVersion]:
        ...

    def get_template_for_version(self, prompt_version_id: str) -> PromptTemplate:
        ...


@dataclass
class PromptRegistry:
    repository: Repository
    prompt_reader: PromptRuntimeReader | None = None

    def resolve_published_version(
        self,
        *,
        node_id: str,
        case_id: str | None = None,
        provider_profile_id: str | None = None,
    ):
        if self.prompt_reader is not None:
            return self.prompt_reader.resolve_published_version(
                node_id=node_id,
                case_id=case_id,
                provider_profile_id=provider_profile_id,
            )
        candidates = [
            binding
            for binding in self.repository.prompt_bindings.values()
            if binding.enabled
            and (binding.node_id is None or binding.node_id == node_id)
            and (binding.case_id is None or binding.case_id == case_id)
            and (
                binding.provider_profile_id is None
                or binding.provider_profile_id == provider_profile_id
            )
        ]
        candidates.sort(key=lambda item: item.priority)
        for binding in candidates:
            version = self.repository.prompt_versions[binding.prompt_version_id]
            if version.status == "published":
                return binding, version
        raise NodeExecutionError(
            ErrorCode.prompt_version_not_published,
            f"No published prompt version is bound to {node_id}.",
        )

    def render(
        self,
        *,
        node_id: str,
        variables: dict,
        case_id: str | None = None,
        run_id: str | None = None,
        node_run_id: str | None = None,
        provider_profile_id: str | None = None,
    ) -> tuple[PromptInvocation, str]:
        binding, version = self.resolve_published_version(
            node_id=node_id,
            case_id=case_id,
            provider_profile_id=provider_profile_id,
        )
        missing = [
            token.split("}", 1)[0]
            for token in version.content.split("{")
            if "}" in token and token.split("}", 1)[0] not in variables
        ]
        if missing:
            raise NodeExecutionError(
                ErrorCode.prompt_render_error,
                f"Missing prompt variables: {', '.join(sorted(missing))}",
                details={"missing": missing},
            )
        rendered = version.content
        for key, value in variables.items():
            rendered = rendered.replace("{" + key + "}", str(value))
        invocation = PromptInvocation(
            id=new_id("prinv"),
            prompt_template_id=binding.prompt_template_id,
            prompt_version_id=version.id,
            case_id=case_id,
            run_id=run_id,
            node_run_id=node_run_id,
            variables_artifact_id=None,
        )
        self.repository.prompt_invocations[invocation.id] = invocation
        return invocation, rendered

    def validate_output(self, *, prompt_version_id: str, output: dict) -> None:
        if self.prompt_reader is not None:
            template = self.prompt_reader.get_template_for_version(prompt_version_id)
        else:
            version = self.repository.prompt_versions[prompt_version_id]
            template = self.repository.prompt_templates[version.prompt_template_id]
        schema_id = template.output_schema_ref.schema_id
        if schema_id == "creative_intent.output":
            intent = output.get("intent")
            if not isinstance(intent, dict):
                raise NodeExecutionError(
                    ErrorCode.prompt_output_invalid,
                    "Creative intent output must contain an intent object.",
                )
            if not isinstance(intent.get("hook"), str) or not isinstance(intent.get("beats"), list):
                raise NodeExecutionError(
                    ErrorCode.prompt_output_invalid,
                    "Creative intent output is missing hook or beats.",
                )
        elif not isinstance(output, dict):
            raise NodeExecutionError(
                ErrorCode.prompt_output_invalid,
                f"Prompt output for schema {schema_id} must be an object.",
            )
