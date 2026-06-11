import type { AgentRun } from "../../api/r6";

export const sourceTypeOptions = [
  { value: "manual_note", label: "手动备注", hint: "粘贴调研结论、投放复盘或客服反馈。" },
  { value: "text", label: "文本资料", hint: "适合粘贴长文、访谈摘录或脚本素材。" },
  { value: "url", label: "网页链接", hint: "仅允许 http(s) 链接，避免内部地址泄漏。" },
  { value: "file", label: "文件产物", hint: "填写已上传 artifact id 或可追踪文件引用。" },
] as const;

export type SourceType = (typeof sourceTypeOptions)[number]["value"];

export const agentGoalOptions = [
  { value: "script_draft", label: "生成脚本草稿" },
  { value: "brief", label: "生成创意简报" },
  { value: "memory_proposal", label: "提出记忆提案" },
] as const;

export function sourceTypeLabel(value: string) {
  return sourceTypeOptions.find((item) => item.value === value)?.label ?? "未知数据源";
}

export function sourceTypeHint(value: string) {
  return sourceTypeOptions.find((item) => item.value === value)?.hint ?? "";
}

export function agentGoalLabel(value: AgentRun["goal"] | string) {
  return agentGoalOptions.find((item) => item.value === value)?.label ?? "智能体运行";
}

export function memoryStatusLabel(value: string) {
  if (value === "proposed") return "待处理";
  if (value === "approved") return "已批准";
  if (value === "active") return "已入库";
  if (value === "rejected") return "已拒绝";
  if (value === "deprecated") return "已停用";
  if (value === "superseded") return "已替代";
  return "未知状态";
}

export function validateSourceRef(type: SourceType, value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "请填写数据源内容或引用";
  if (type !== "url") return null;
  try {
    const url = new URL(trimmed);
    if (url.protocol === "http:" || url.protocol === "https:") return null;
  } catch {
    return "请输入有效的 http(s) 链接";
  }
  return "仅允许 http(s) 链接";
}
