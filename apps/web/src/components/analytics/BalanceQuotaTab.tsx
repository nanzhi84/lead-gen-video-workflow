import { AlertCircle, CheckCircle2, HelpCircle, KeyRound, RefreshCw, WalletCards } from "lucide-react";
import type { ProviderBalanceItem, ProviderBalanceReport } from "../../api/r6";
import { TimeText } from "../TimeText";
import { formatMoney, providerBalanceStatusLabels } from "./analyticsModel";

const STATUS_CLASSES: Record<ProviderBalanceItem["status"], string> = {
  ok: "border-status-success/25 bg-status-success/10 text-status-success",
  unconfigured: "border-status-warning/25 bg-status-warning/10 text-status-warning",
  unsupported: "border-border bg-white/65 text-text-secondary",
  unauthorized: "border-status-error/25 bg-status-error/10 text-status-error",
  error: "border-status-error/25 bg-status-error/10 text-status-error",
  pending: "border-status-info/25 bg-status-info/10 text-status-info",
};

function statusIcon(status: ProviderBalanceItem["status"]) {
  if (status === "ok") return CheckCircle2;
  if (status === "unconfigured" || status === "unauthorized") return KeyRound;
  if (status === "error") return AlertCircle;
  return HelpCircle;
}

function formatQuota(item: ProviderBalanceItem) {
  if (typeof item.quota_remaining !== "number") return "暂无";
  const unit = item.unit ? ` ${item.unit}` : "";
  return `${item.quota_remaining.toLocaleString("zh-CN")}${unit}`;
}

function providerLabel(providerId: string) {
  if (providerId === "aliyun.billing") return "阿里云 / DashScope";
  if (providerId === "volcengine.billing") return "火山引擎";
  if (providerId === "openai.image") return "OpenAI 图片";
  if (providerId === "runninghub.heygem") return "RunningHub HeyGem";
  if (providerId === "minimax.tts") return "MiniMax";
  return providerId;
}

function accountLabel(item: ProviderBalanceItem) {
  if (item.account_group === "aliyun.shared") return "共享账户";
  if (item.account_group === "volcengine.shared") return "共享账户";
  return item.account_group ?? "default";
}

function EmptyPanel({ status }: { status?: ProviderBalanceReport["status"] }) {
  return (
    <div className="rounded-[22px] border border-dashed border-border bg-white/45 px-6 py-10 text-center text-sm text-text-tertiary">
      {status === "pending" ? "暂无余额快照，请手动刷新后查看" : "暂无余额或配额数据"}
    </div>
  );
}

export function BalanceQuotaTab({
  report,
  isRefreshing,
  onRefresh,
}: {
  report?: ProviderBalanceReport;
  isRefreshing: boolean;
  onRefresh: () => void;
}) {
  const items = report?.items ?? [];

  return (
    <section className="card p-5 md:p-6">
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-xl font-semibold text-text-primary">
            <WalletCards className="h-5 w-5 text-accent" />
            余额&配额
          </h2>
          <p className="mt-1 text-sm text-text-secondary">来自 provider_balance_snapshots 的最新快照</p>
        </div>
        <button className="btn-secondary text-sm" type="button" onClick={onRefresh} disabled={isRefreshing}>
          <RefreshCw className={`h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} />
          立即刷新
        </button>
      </div>

      {items.length === 0 ? (
        <EmptyPanel status={report?.status} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-separate border-spacing-0 text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-text-tertiary">
              <tr>
                <th className="border-b border-border/70 pb-3 font-medium">供应商</th>
                <th className="border-b border-border/70 pb-3 font-medium">账户</th>
                <th className="border-b border-border/70 pb-3 font-medium">余额</th>
                <th className="border-b border-border/70 pb-3 font-medium">配额</th>
                <th className="border-b border-border/70 pb-3 font-medium">状态</th>
                <th className="border-b border-border/70 pb-3 font-medium">检查时间</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {items.map((item) => {
                const Icon = statusIcon(item.status);
                return (
                  <tr key={`${item.provider_id}:${item.account_group ?? "default"}`}>
                    <td className="py-4 pr-4">
                      <p className="font-medium text-text-primary">{providerLabel(item.provider_id)}</p>
                      <p className="font-mono text-xs text-text-tertiary">{item.provider_id}</p>
                    </td>
                    <td className="py-4 pr-4 text-xs text-text-secondary">{accountLabel(item)}</td>
                    <td className="py-4 pr-4 font-mono text-text-primary">{item.balance ? formatMoney(item.balance) : "暂无"}</td>
                    <td className="py-4 pr-4 font-mono text-text-primary">{formatQuota(item)}</td>
                    <td className="py-4 pr-4">
                      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${STATUS_CLASSES[item.status]}`}>
                        <Icon className="h-3.5 w-3.5" />
                        {providerBalanceStatusLabels[item.status]}
                      </span>
                      {item.detail ? <p className="mt-1 max-w-[220px] truncate text-xs text-text-tertiary">{item.detail}</p> : null}
                    </td>
                    <td className="py-4 pr-4 text-text-secondary">
                      <TimeText value={item.checked_at} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
