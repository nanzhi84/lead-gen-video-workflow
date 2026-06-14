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
  { key: "script", label: "脚本工作台", prefix: "prompt.script." },
  { key: "vlm", label: "视频分析 VL", prefix: "prompt.vlm." },
  { key: "cover", label: "发布封面", prefix: "prompt.cover." },
  { key: "editing", label: "剪辑 Agent", prefix: "prompt.editing." },
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
