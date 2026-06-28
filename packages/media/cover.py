"""Cover image domain logic: frame extraction selection + AI cover prompt build.

The frame-based cover (extract a representative thumbnail) is the default,
free, non-fabricated cover. The AI cover prompt builder here is a faithful port
of the production ``AICoverService._build_cover_prompt`` shape: it renders the
seeded ``prompt.cover.ai_cover`` template (the calibration) with explicit
style/source-frame guidance branches.

This module is provider-agnostic and side-effect free: it only assembles the
text prompt. The actual paid image-generation call lives behind an
``image.generate`` provider plugin and is gated in the cover node.
"""

from __future__ import annotations

from dataclasses import dataclass

# Default publish-cover target: vertical short-video 9:16.
DEFAULT_COVER_SIZE = "1080x1920"
# Seedream rejects smaller custom sizes; 1440x2560 is exact 9:16 at its minimum
# accepted custom-pixel threshold. The provider output is still normalized to
# ``DEFAULT_COVER_SIZE`` before storage.
SEEDREAM_COVER_REQUEST_SIZE = "1440x2560"
_TITLE_MAX_CHARS = 32
_SUBTITLE_MAX_CHARS = 32
_DESCRIPTION_MAX_CHARS = 900
_TAG_MAX = 6

# Fallback template used only when the seeded ``prompt.cover.ai_cover`` template is
# unavailable. Keep it compact: the provider should spend tokens on concrete cover
# information, not repeated guardrails.
DEFAULT_AI_COVER_PROMPT_TEMPLATE = """生成一张 9:16 竖版中文短视频封面，尺寸 {size}。
{style_reference}
{source_frame_reference}

封面文案：
- 主标题必须逐字使用：「{title}」
{subtitle_instruction}

业务信息：
- 案例：{case_name}
- 发布摘要：{description}
- 标签：{tags}

设计要求：
- 做成有明确视觉设计的抖音本地生活封面，不是普通截图贴字；需要有商业包装感、视觉冲击和清楚层级。
- 具体构图、字体、色彩、装饰元素、光影和排版由模型自主设计，但必须让主标题和副标题在手机缩略图里一眼可读。
- 参考图只提供人物/车辆/门店/产品等真实主体和场景基础；可以重新裁切、调光、强化主体和背景层次。
- 参考图只用于主体、场景、构图和风格；保留真实人物、车辆、门店、产品，不照抄旧文案、Logo 或账号。
- 不加水印、二维码、平台标识、假账号、长段落；最终只输出单张封面图。{prompt_extra}"""


@dataclass(frozen=True)
class CoverPromptInputs:
    title: str
    description: str = ""
    tags: tuple[str, ...] = ()
    case_name: str | None = None
    subtitle: str | None = None
    prompt_extra: str | None = None
    has_source_frame: bool = False
    has_template: bool = False
    style_guidance: str | None = None
    size: str = DEFAULT_COVER_SIZE


def build_cover_prompt(inputs: CoverPromptInputs, *, template: str | None = None) -> str:
    """Render the AI cover prompt. ``template`` is the seeded prompt content;
    falls back to the origin default template when omitted."""
    clean_title = (inputs.title or "").strip()[:_TITLE_MAX_CHARS] or "精彩案例"
    clean_subtitle = (inputs.subtitle or "").strip()[:_SUBTITLE_MAX_CHARS]
    clean_description = (inputs.description or "").strip()
    if len(clean_description) > _DESCRIPTION_MAX_CHARS:
        clean_description = clean_description[:_DESCRIPTION_MAX_CHARS] + "..."
    tag_line = "、".join([tag.strip("# ") for tag in inputs.tags if tag.strip("# ")][:_TAG_MAX])

    variables = {
        "size": inputs.size,
        "style_reference": _style_reference(inputs),
        "source_frame_reference": _source_frame_reference(inputs),
        "title": clean_title,
        "subtitle": clean_subtitle,
        "subtitle_instruction": _subtitle_instruction(clean_subtitle),
        "case_name": inputs.case_name or "未指定",
        "description": clean_description or "无",
        "tags": tag_line or "无",
        "prompt_extra": _prompt_extra(inputs.prompt_extra),
    }
    return _render_template(template or DEFAULT_AI_COVER_PROMPT_TEMPLATE, variables)


def _style_reference(inputs: CoverPromptInputs) -> str:
    if inputs.style_guidance:
        return (
            "参考图用于学习封面风格：复用其构图、字级、色彩、留白和商业质感，"
            "不要照抄旧文字、Logo 或账号。\n参考风格说明：\n"
            f"{inputs.style_guidance}"
        )
    if inputs.has_template:
        return (
            "有封面模板参考：学习其视觉层级、字体气质、色彩、留白和商业质感，"
            "不要照抄旧文字、Logo 或账号。"
        )
    return "无封面模板参考：从参考帧重新设计爆款封面版式，不要只在原图上贴普通文字。"


def _source_frame_reference(inputs: CoverPromptInputs) -> str:
    if inputs.has_source_frame and inputs.has_template:
        return (
            "参考图是双栏图：左侧为风格模板，右侧为视频帧。"
            "以右侧视频帧的人物、车辆、场景为主体，左侧只参考版式风格。"
        )
    if inputs.has_source_frame:
        return (
            "参考图是本条视频选中的人像/场景帧，请以其中的人物、车辆和场景作为封面主体；"
            "允许重新裁切、调光和做商业化视觉设计。"
        )
    return "没有可用视频帧参考，请根据业务信息生成汽车本地服务封面主体。"


def _subtitle_instruction(clean_subtitle: str) -> str:
    if clean_subtitle:
        return f"- 副标题如使用，必须逐字使用：「{clean_subtitle}」"
    return "- 不要额外编造中文卖点；确有必要时只补一个极短利益点。"


def _prompt_extra(prompt_extra: str | None) -> str:
    if prompt_extra and prompt_extra.strip():
        return f"\n补充要求：{prompt_extra.strip()}"
    return ""


def _render_template(template: str, variables: dict[str, str]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", str(value))
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered
