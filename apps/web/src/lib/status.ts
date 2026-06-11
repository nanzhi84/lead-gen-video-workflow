import {
  AlertCircle,
  CheckCircle2,
  Clock,
  HelpCircle,
  Loader2,
  PauseCircle,
  XCircle,
  type LucideIcon,
} from "lucide-react";

export type Tone = "success" | "warning" | "error" | "info" | "muted" | "processing";

export type StatusPresentation = {
  label: string;
  tone: Tone;
  icon: LucideIcon;
  spinning?: boolean;
};

const PRESENTATIONS: Record<string, StatusPresentation> = {
  created: { label: "已创建", tone: "info", icon: Clock },
  admitted: { label: "已入队", tone: "info", icon: Clock },
  running: { label: "运行中", tone: "processing", icon: Loader2, spinning: true },
  cancelling: { label: "中断中", tone: "warning", icon: Loader2, spinning: true },
  succeeded: { label: "已完成", tone: "success", icon: CheckCircle2 },
  failed: { label: "失败", tone: "error", icon: AlertCircle },
  cancelled: { label: "中断成功", tone: "success", icon: XCircle },
  pending: { label: "等待中", tone: "muted", icon: Clock },
  skipped: { label: "已跳过", tone: "muted", icon: PauseCircle },
  degraded: { label: "降级完成", tone: "warning", icon: AlertCircle },
  passed: { label: "通过", tone: "success", icon: CheckCircle2 },
  warning: { label: "有警告", tone: "warning", icon: AlertCircle },
  active: { label: "启用中", tone: "success", icon: CheckCircle2 },
  disabled: { label: "已禁用", tone: "muted", icon: PauseCircle },
  expired: { label: "已过期", tone: "warning", icon: AlertCircle },
  draft: { label: "草稿", tone: "muted", icon: Clock },
  approved: { label: "已审批", tone: "info", icon: CheckCircle2 },
  published: { label: "已发布", tone: "success", icon: CheckCircle2 },
  archived: { label: "已归档", tone: "muted", icon: PauseCircle },
  local: { label: "本地", tone: "muted", icon: HelpCircle },
  dev: { label: "开发", tone: "info", icon: HelpCircle },
  staging: { label: "预发", tone: "warning", icon: HelpCircle },
  prod: { label: "生产", tone: "success", icon: HelpCircle },
  input_token: { label: "输入 Token", tone: "muted", icon: HelpCircle },
  output_token: { label: "输出 Token", tone: "muted", icon: HelpCircle },
  media_second: { label: "媒体秒", tone: "muted", icon: HelpCircle },
  call: { label: "调用", tone: "muted", icon: HelpCircle },
};

export function getStatusPresentation(status?: string | null): StatusPresentation {
  if (!status) return { label: "未知", tone: "muted", icon: HelpCircle };
  return PRESENTATIONS[status] ?? { label: `未知状态`, tone: "muted", icon: HelpCircle };
}

export const toneClassNames: Record<Tone, string> = {
  success: "border-status-success/20 bg-status-success/10 text-status-success",
  warning: "border-status-warning/25 bg-status-warning/10 text-status-warning",
  error: "border-status-error/25 bg-status-error/10 text-status-error",
  info: "border-status-info/25 bg-status-info/10 text-status-info",
  muted: "border-border/70 bg-white/60 text-text-secondary",
  processing: "border-accent/20 bg-accent/10 text-accent",
};

export const toneDotClassNames: Record<Tone, string> = {
  success: "bg-status-success",
  warning: "bg-status-warning",
  error: "bg-status-error",
  info: "bg-status-info",
  muted: "bg-text-tertiary",
  processing: "bg-accent",
};

export function labelForStatus(status?: string | null) {
  return getStatusPresentation(status).label;
}
