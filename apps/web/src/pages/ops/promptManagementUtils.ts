import type { PromptBindingView, PromptTemplateView } from "../../api/client";

export type TemplateForm = {
  name: string;
  purpose: string;
  variables_schema_id: string;
  output_schema_id: string;
};

export type BindingForm = {
  case_id: string;
  node_id: string;
  priority: number;
};

export const emptyTemplate: TemplateForm = {
  name: "",
  purpose: "",
  variables_schema_id: "prompt.variables",
  output_schema_id: "prompt.output",
};

export const emptyBinding: BindingForm = { case_id: "", node_id: "", priority: 100 };

export const flow = ["draft", "reviewing", "approved", "published"] as const;

export const promptGroups = [
  { key: "script", label: "脚本生成", prefix: "prompt.script." },
  { key: "vlm", label: "视频理解", prefix: "prompt.vlm." },
  { key: "cover", label: "发布封面", prefix: "prompt.cover." },
  { key: "editing", label: "剪辑助手", prefix: "prompt.editing." },
] as const;

export type PromptGroupKey = (typeof promptGroups)[number]["key"];

export const statusLabel: Record<string, string> = {
  draft: "草稿",
  reviewing: "审批中",
  approved: "已审批",
  published: "已发布",
  active: "启用",
  deprecated: "已弃用",
  rolled_back: "已回滚",
};

export function variableChips(template?: PromptTemplateView) {
  const hinted = template?.variable_hints ?? [];
  if (hinted.length > 0) return Array.from(new Set(hinted));
  const source = template?.template.variables_schema_ref.schema_id ?? "";
  const inferred = source
    .split(/[._:-]/)
    .filter((part) => part.length > 2 && !["variables", "schema"].includes(part));
  return Array.from(new Set(["case_name", "product", "target_audience", "script", "topic", ...inferred]));
}

export function diffRows(base = "", next = "") {
  const left = base.split("\n");
  const right = next.split("\n");
  const rows: Array<{ kind: "same" | "remove" | "add"; text: string }> = [];
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    if (left[index] === right[index]) {
      if (left[index]) rows.push({ kind: "same", text: left[index] });
      continue;
    }
    if (left[index]) rows.push({ kind: "remove", text: left[index] });
    if (right[index]) rows.push({ kind: "add", text: right[index] });
  }
  return rows.slice(0, 80);
}

export function schemaText(ref: { schema_id: string; schema_version?: string }) {
  return `${ref.schema_id}@${ref.schema_version ?? "v1"}`;
}

export function bindingSummary(items: PromptBindingView[], templateId: string) {
  const matched = items.filter((item) => item.binding.prompt_template_id === templateId);
  if (matched.length === 0) return "未绑定";
  const first = matched[0].binding.node_id || "全局节点";
  return matched.length > 1 ? `用于 ${first} 等 ${matched.length} 处` : `用于 ${first}`;
}

export type TemplateUsage = {
  inProduction: boolean;
  label: string;
  nodeName: string;
  enabledCount: number;
};

/**
 * 生产使用状态：只有“已启用 + 绑定到生产节点”的模板才会被生产管线使用。
 * 绿色「生产使用中」= 至少有一条 enabled 的绑定；灰色「未接入生产」= 没有任何 enabled 绑定。
 */
export function templateUsage(items: PromptBindingView[], templateId: string): TemplateUsage {
  const matched = items.filter((item) => item.binding.prompt_template_id === templateId);
  const enabled = matched.filter((item) => item.binding.enabled);
  if (enabled.length === 0) {
    return { inProduction: false, label: "未接入生产", nodeName: "", enabledCount: 0 };
  }
  const node = enabled[0].binding.node_id || "全局节点";
  const label = enabled.length > 1 ? `生产使用中 · ${node} 等 ${enabled.length} 处` : `生产使用中 · ${node}`;
  return { inProduction: true, label, nodeName: node, enabledCount: enabled.length };
}

export const BINDING_EXPLAINER =
  "绑定 = 把某个已发布版本接到生产节点；只有绑定后的提示词才会被生产管线使用。";

// ───────────────────────── 用户友好层 ─────────────────────────
// 把后端的 purpose / node_id / 变量占位符翻译成业务语言，让非技术用户看得懂。

const PERSONA_LABELS: Record<string, string> = {
  hard_ad: "硬广投流",
  ip_persona: "IP 人设号",
};

const OPERATION_LABELS: Record<string, string> = {
  polish: "润色",
  fresh: "全新创作",
  fresh_generate: "全新创作",
  remix: "参考爆款",
  remix_generate: "参考爆款",
  clone: "爆款复刻",
  clone_generate: "爆款复刻",
  generate: "通用生成",
  semantic: "语义结构包",
};

const VLM_FLAVOR_LABELS: Record<string, string> = {
  analysis: "通用分析",
  portrait: "人像理解",
  scenery: "空镜 / 场景",
  broll_analysis: "通用分析",
  broll_portrait: "人像理解",
  broll_scenery: "空镜 / 场景",
};

const COVER_LABELS: Record<string, string> = {
  ai_cover: "AI 封面图",
  reference_style: "参考风格解析",
};

/** 把提示词的 purpose 翻译成「业务标题 + 用途说明」。 */
export function describePrompt(purpose: string, fallbackName: string): { title: string; usage: string } {
  const segments = purpose.split(".");
  // prompt.script.{persona}.{operation}
  if (purpose.startsWith("prompt.script.") && segments.length >= 4) {
    const persona = PERSONA_LABELS[segments[2]] ?? segments[2];
    const operation = OPERATION_LABELS[segments[3]] ?? segments[3];
    return { title: `${persona} · ${operation}`, usage: `用于「${persona}」场景下的「${operation}」口播脚本生成。` };
  }
  // prompt.vlm.broll_xxx
  if (purpose.startsWith("prompt.vlm.")) {
    const flavor = VLM_FLAVOR_LABELS[segments[2]] ?? segments[2];
    return { title: `B-roll 视频理解 · ${flavor}`, usage: `分析 B-roll 素材，产出「${flavor}」维度的视频理解标注。` };
  }
  // prompt.cover.xxx
  if (purpose.startsWith("prompt.cover.")) {
    const type = COVER_LABELS[segments[2]] ?? segments[2];
    return { title: `发布封面 · ${type}`, usage: `发布环节生成封面时使用，对应「${type}」。` };
  }
  if (purpose.startsWith("prompt.editing.")) {
    return { title: fallbackName || "剪辑助手", usage: "剪辑 Agent 在自动剪辑环节使用。" };
  }
  if (purpose === "case_agent.script_generate") {
    return { title: "脚本生成（通用兜底）", usage: "脚本生成的通用提示词，未匹配到具体人设/操作时使用。" };
  }
  if (purpose === "media.vlm_annotation") {
    return { title: "素材视频理解（通用兜底）", usage: "素材视频理解的通用提示词，未匹配到具体类型时使用。" };
  }
  return { title: fallbackName || purpose, usage: "AI 生产环节使用的提示词。" };
}

/** 变量占位符 → 中文说明，用于「字段说明」图例。 */
export const VARIABLE_LABELS: Record<string, string> = {
  case_name: "案例 / 商家名称",
  product_name: "产品或服务名称",
  industry: "所属行业或品类",
  target_audience: "目标人群 / 受众画像",
  ip_persona: "IP 人设 / 账号设定",
  brand_voice: "品牌说话语调和风格",
  key_selling_points: "核心卖点 / 产品优势",
  description: "案例 / 视频详细描述",
  strategy_tags: "创意策略标签",
  scene_type: "视频场景类型",
  scene_label: "场景标签 / 名称",
  duration: "视频时长偏好",
  generation_mode: "创作模式（全新 / 参考 / 复刻）",
  variation_count: "生成版本数量",
  style: "内容 / 视觉风格偏好",
  user_input: "用户输入的初稿或补充",
  original_script: "待润色 / 参考的原始脚本",
  reference_script: "对标参考文案",
  title: "视频 / 封面标题",
  script: "口播脚本内容",
  publish_content: "平台发布简介",
  asset_id: "素材唯一标识",
  asset_kind: "素材类型（视频 / 图片 / 音频）",
  analysis_type: "视频理解分析维度",
  style_reference: "封面风格参考",
  source_frame_reference: "源视频帧 / 图片参考",
  tags: "标签集合",
  subtitle_instruction: "封面副标题指示",
  prompt_extra: "额外补充指令",
  brief: "创意简报 / 投放 Brief",
  memories: "案例历史记忆 / 背景",
};

export function variableLabel(name: string): string {
  return VARIABLE_LABELS[name] ?? name;
}

/** 从提示词内容里提取实际出现的占位符（兼容 {x} 与 {{x}}），用于字段说明图例。 */
export function usedVariables(content: string): string[] {
  const names = new Set<string>();
  const re = /\{\{?\s*([a-zA-Z0-9_]+)\s*\}?\}/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(content)) !== null) {
    names.add(match[1]);
  }
  return Array.from(names);
}
