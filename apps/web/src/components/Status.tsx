import type { NodeRun, RunCard } from "../api/client";

const RUN_LABELS: Record<RunCard["status"], string> = {
  created: "已创建",
  admitted: "已入队",
  running: "运行中",
  cancelling: "取消中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const NODE_LABELS: Record<NodeRun["status"], string> = {
  pending: "等待中",
  running: "运行中",
  succeeded: "成功",
  failed: "失败",
  skipped: "跳过",
  degraded: "降级",
  cancelled: "已取消",
};

export function StatusPill({ status }: { status: RunCard["status"] | NodeRun["status"] | string }) {
  const label = RUN_LABELS[status as RunCard["status"]] ?? NODE_LABELS[status as NodeRun["status"]] ?? status;
  return (
    <span className={`statusPill ${status}`}>
      <i />
      {label}
    </span>
  );
}
