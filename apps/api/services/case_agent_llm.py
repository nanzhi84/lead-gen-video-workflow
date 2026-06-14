from __future__ import annotations

import json
import re

from fastapi import Request

from apps.api.common import get_case, provider_repository, repository
from packages.ai.gateway import ProviderCall
from packages.ai.prompts.registry import case_prompt_variables
from packages.core import contracts as c
from packages.core.config.settings import sandbox_fallback_allowed
from packages.core.workflow import NodeExecutionError

# The merged/legacy prompt that every persona×operation variant falls back to when
# no published binding exists for the variant node (or that binding's content cannot
# be rendered against the variables we have). Keeps generation alive ("保证不挂").
_FALLBACK_SCRIPT_NODE_ID = "CaseAgentScriptGenerate"

# Prompt-resolution failures that should trigger the fallback instead of bubbling up:
# - version_not_published: no binding (or no published version) for the variant node.
# - render_error: a binding exists but its real-prompt content references tokens we do
#   not supply (e.g. {{variation_count}}, {{user_input}}, or embedded JSON braces), so
#   the variant template is incompatible with this call site -> degrade to the merged one.
_FALLBACK_ERROR_CODES = frozenset(
    {c.ErrorCode.prompt_version_not_published, c.ErrorCode.prompt_render_error}
)


# Single-script JSON output contract appended to every rendered prompt. The migrated
# persona×operation prompt bodies describe the creative task but not the output shape
# (the legacy system appended its own contract at runtime); we generate one script per
# call (the UI loops for N variations), so we ask for a single {script} object that
# _script_from_llm_output can parse.
_RESPONSE_CONTRACT = (
    '请只返回一个 JSON 对象：{"script": "<一条可直接拍摄的完整中文口播脚本纯文本>"}。'
    "script 必须是数字人主播从头到尾逐字念出来的口播台词，"
    "严禁出现任何括号（包括中文（）和英文()）以及括号内的镜头、画面、景别、动作、表情、"
    "手势、语气、停顿、节奏、配乐、音效、字幕、分镜或旁白等提示——"
    "不要写「（停顿）」「（直视镜头）」「（语气转沉稳）」「（靠近镜头）」这类内容，只输出要念出来的话本身。"
    "只输出这一个脚本，不要输出思考过程、解释说明或多余文字。"
)


def generate_script_with_llm(
    case_id: str,
    brief: str,
    memory_ids: list[str],
    memories: list[str],
    request: Request,
    persona_mode: str = "hard_ad",
    operation: str = "generate",
    strategy_tags: list[str] | None = None,
    reference_script: str | None = None,
    duration: str | None = None,
) -> str | None:
    profile = _select_real_llm_profile(request)
    if profile is None:
        # No real llm.chat provider is armed. Production fails loudly rather than
        # echoing the brief back as a stub draft (the old silent fallback). The
        # test suite opts into the sandbox/stub path via the flag.
        if not sandbox_fallback_allowed():
            raise NodeExecutionError(
                c.ErrorCode.provider_unsupported_option,
                "未配置可用的真实 LLM 供应商（llm.chat），无法生成脚本。请在「设置」中配置并启用真实 LLM 供应商及密钥。",
            )
        return None
    # #B prompt wiring: fill the case profile vocabulary ({case_name}{product_name}
    # {industry}{target_audience}{ip_persona}{brand_voice}{key_selling_points}
    # {description}{tags}) so downstream templates no longer get permanent empties.
    # render() only substitutes tokens the template references, so these extras are
    # harmless for templates (like CaseAgentScriptGenerate) that ignore them.
    tags = strategy_tags or []
    scene_label = "硬广投流" if persona_mode == "hard_ad" else "IP人设号"
    variables: dict[str, object] = {
        "brief": brief,
        "memories": " / ".join(memories) if memories else "暂无",
        "persona_mode": persona_mode,
        "operation": operation,
        # 结构化创作变量：persona×operation 真实提示词按 {{...}} 引用这些键，缺任一键即触发
        # prompt_render_error 并兜底到通用提示词（脚本就失去案例上下文）。全量提供以保证渲染。
        "variation_count": "1",
        "scene_type": persona_mode,
        "scene_label": scene_label,
        "generation_mode": operation,
        "strategy_tags": "、".join(tags),
        "duration": duration or "",
        "user_input": reference_script or "",
        "original_script": reference_script or "",
        "style": "",
        "title": "",
        "script": "",
        "publish_content": "",
    }
    variables.update(case_prompt_variables(get_case(request, case_id)))
    # 卖点为空时退化到案例描述（对齐 mac mini），避免脚本缺乏卖点支撑。
    if not str(variables.get("key_selling_points") or "").strip():
        variables["key_selling_points"] = variables.get("description") or ""
    # Route to the persona×operation variant node first; fall back to the merged
    # CaseAgentScriptGenerate prompt when the variant has no published binding or its
    # content cannot be rendered against these variables.
    variant_node_id = f"{_FALLBACK_SCRIPT_NODE_ID}.{persona_mode}.{operation}"
    prompt_invocation, rendered = _render_with_fallback(
        request,
        variant_node_id=variant_node_id,
        variables=variables,
        case_id=case_id,
        provider_profile_id=profile.id,
    )
    rendered = f"{rendered}\n\n{_RESPONSE_CONTRACT}"
    invocation, result = request.app.state.provider_gateway.invoke(
        ProviderCall(
            case_id=case_id,
            provider_profile_id=profile.id,
            capability_id="llm.chat",
            prompt_version_id=prompt_invocation.prompt_version_id,
            input={"prompt": rendered, "brief": brief, "memory_ids": memory_ids, "memories": memories},
        )
    )
    if result is None or invocation.error:
        raise NodeExecutionError(
            invocation.error.code if invocation.error else c.ErrorCode.provider_remote_failed,
            invocation.error.message if invocation.error else "Case agent LLM provider failed.",
        )
    repository(request).prompt_invocations[prompt_invocation.id] = prompt_invocation.model_copy(
        update={"provider_invocation_id": invocation.id, "updated_at": c.utcnow()}
    )
    script = _strip_stage_cues(_script_from_llm_output(result.output))
    if not script:
        raise NodeExecutionError(c.ErrorCode.provider_remote_failed, "Case agent LLM output missing script.")
    return script


def _render_with_fallback(
    request: Request,
    *,
    variant_node_id: str,
    variables: dict[str, object],
    case_id: str,
    provider_profile_id: str,
):
    """Render the variant prompt node, degrading to the merged node when it is
    unavailable or incompatible.

    The fallback covers two distinct failures (see ``_FALLBACK_ERROR_CODES``): the
    variant node has no published binding yet, or the bound (real, migrated) prompt
    references tokens this call site does not provide. In both cases we re-render
    against ``CaseAgentScriptGenerate`` so script generation never hard-fails on a
    missing/incompatible variant. Any other error (e.g. provider/output issues) is
    re-raised unchanged.
    """
    registry = request.app.state.prompt_registry
    try:
        return registry.render(
            node_id=variant_node_id,
            variables=variables,
            case_id=case_id,
            provider_profile_id=provider_profile_id,
        )
    except NodeExecutionError as exc:
        if exc.error.code not in _FALLBACK_ERROR_CODES:
            raise
    return registry.render(
        node_id=_FALLBACK_SCRIPT_NODE_ID,
        variables=variables,
        case_id=case_id,
        provider_profile_id=provider_profile_id,
    )


def _select_real_llm_profile(request: Request) -> c.ProviderProfile | None:
    gateway = request.app.state.provider_gateway
    # Read the DB-backed provider repository when present (SQLAlchemy backend) so we
    # see the SAME armed real profiles the providers endpoint and the pipeline use.
    # The in-memory ``repository.provider_profiles`` twin is only seed defaults and
    # is stale once a secret is armed via the API — reading it here is what made
    # script generation silently fall back to the brief-echo stub.
    provider_repo = provider_repository(request)
    if provider_repo is not None:
        candidates = provider_repo.list_profiles(capability="llm.chat", limit=200)
    else:
        candidates = [
            profile
            for profile in repository(request).provider_profiles.values()
            if profile.capability == "llm.chat"
        ]
    for profile in candidates:
        if not profile.enabled or profile.provider_id == "sandbox":
            continue
        if profile.provider_id not in gateway.plugins:
            continue
        if profile.secret_ref and not gateway._secret_is_active(profile.secret_ref):
            continue
        return profile
    return None


# Stage-direction cues that must never appear in the spoken 口播 output. We strip a
# parenthetical group only when its content reads like a camera/action/tone/pacing
# direction (keeps legitimate spoken asides like "（仅限前200名）" intact). Belt-and-
# suspenders on top of the prompt's no-parenthetical instruction.
_STAGE_CUE_KEYWORDS = (
    "停顿", "镜头", "语气", "画面", "景别", "特写", "近景", "远景", "全景", "转场",
    "配乐", "bgm", "音效", "字幕", "分镜", "旁白", "画外", "动作", "表情", "手势",
    "节奏", "语速", "拉近", "靠近", "直视", "对镜", "微笑", "点头", "停留", "切到",
    "运镜", "光线", "出镜", "入镜",
)


def _strip_stage_cues(text: str) -> str:
    """Remove stage-direction parentheticals (（…）/(…)) from a spoken script."""
    def _repl(match: re.Match) -> str:
        inner = match.group(1).lower()
        return "" if any(keyword in inner for keyword in _STAGE_CUE_KEYWORDS) else match.group(0)

    text = re.sub(r"（([^（）]*)）", _repl, text)
    text = re.sub(r"\(([^()]*)\)", _repl, text)
    # tidy whitespace left behind by removed cues
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _script_from_llm_output(output: dict) -> str:
    # Some persona prompts answer with the legacy {"items":[{"script":...}]} contract;
    # take the first item's script when present.
    items = output.get("items")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        for nested_key in ("script", "content", "draft"):
            nested = items[0].get(nested_key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    for key in ("script", "draft", "polished_script", "content"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            if key == "content":
                parsed = _json_object(value)
                for nested_key in ("script", "draft", "polished_script"):
                    nested = parsed.get(nested_key)
                    if isinstance(nested, str) and nested.strip():
                        return nested.strip()
            return value.strip()
    return ""


def _json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
