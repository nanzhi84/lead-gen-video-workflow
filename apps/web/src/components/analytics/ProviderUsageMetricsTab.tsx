import { BarChart3, DollarSign, Percent, PhoneCall } from "lucide-react";
import type { ProviderUsageMetricsItem, ProviderUsageMetricsReport } from "../../api/r6";
import { formatMoney, formatRate } from "./analyticsModel";

function EmptyPanel() {
  return (
    <div className="rounded-[22px] border border-dashed border-border bg-white/45 px-6 py-10 text-center text-sm text-text-tertiary">
      当前时间范围内暂无 provider 调用记录
    </div>
  );
}

function UsageBars({ items }: { items: ProviderUsageMetricsItem[] }) {
  const topItems = items.slice(0, 8);
  const maxCalls = Math.max(0, ...topItems.map((item) => item.calls));
  if (maxCalls === 0) return <EmptyPanel />;
  const width = 560;
  const rowHeight = 34;
  const chartHeight = topItems.length * rowHeight + 24;

  return (
    <svg className="h-auto w-full overflow-visible" viewBox={`0 0 ${width} ${chartHeight}`} role="img" aria-label="API 调用量条形图">
      {topItems.map((item, index) => {
        const y = index * rowHeight + 8;
        const barWidth = Math.max(8, (item.calls / maxCalls) * 310);
        const label = `${item.provider_id} / ${item.capability_id}`;
        return (
          <g key={`${item.provider_id}:${item.capability_id}:${item.model_id ?? "all"}`}>
            <text x="0" y={y + 17} className="fill-text-secondary text-[12px]">
              {label.length > 30 ? `${label.slice(0, 29)}...` : label}
            </text>
            <rect x="245" y={y} width="315" height="20" rx="10" fill="#edf0e8" />
            <rect x="245" y={y} width={barWidth} height="20" rx="10" fill="#5e6d51">
              <title>{`${label}: ${item.calls} calls`}</title>
            </rect>
            <text x={Math.min(548, 253 + barWidth)} y={y + 15} textAnchor="end" className="fill-text-primary text-[12px] font-semibold">
              {item.calls.toLocaleString("zh-CN")}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function ProviderUsageMetricsTab({
  report,
  windowHours,
}: {
  report?: ProviderUsageMetricsReport;
  windowHours: number;
}) {
  const items = [...(report?.items ?? [])].sort((left, right) => right.calls - left.calls);
  const totalCalls = items.reduce((sum, item) => sum + item.calls, 0);
  const totalSuccess = items.reduce((sum, item) => sum + item.success_count, 0);
  const totalCost = items.reduce((sum, item) => sum + Number(item.estimated_cost.amount), 0);
  const currency = items[0]?.estimated_cost.currency ?? "CNY";

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_390px]">
      <section className="card p-5 md:p-6">
        <div className="mb-5">
          <h2 className="flex items-center gap-2 text-xl font-semibold text-text-primary">
            <BarChart3 className="h-5 w-5 text-accent" />
            API 用量监控
          </h2>
          <p className="mt-1 text-sm text-text-secondary">最近 {windowHours} 小时，按 provider × capability × model 聚合</p>
        </div>
        {items.length === 0 ? <EmptyPanel /> : <UsageBars items={items} />}
      </section>

      <aside className="space-y-5">
        <section className="card p-5">
          <h2 className="text-xl font-semibold text-text-primary">汇总</h2>
          <div className="mt-4 divide-y divide-border/60 border-t border-border/60 text-sm">
            <div className="flex items-center justify-between gap-3 py-3">
              <span className="inline-flex items-center gap-2 text-text-secondary">
                <PhoneCall className="h-4 w-4 text-accent" />
                调用次数
              </span>
              <span className="font-mono text-text-primary">{totalCalls.toLocaleString("zh-CN")}</span>
            </div>
            <div className="flex items-center justify-between gap-3 py-3">
              <span className="inline-flex items-center gap-2 text-text-secondary">
                <Percent className="h-4 w-4 text-status-success" />
                成功率
              </span>
              <span className="font-mono text-text-primary">{formatRate(totalCalls ? totalSuccess / totalCalls : null)}</span>
            </div>
            <div className="flex items-center justify-between gap-3 py-3">
              <span className="inline-flex items-center gap-2 text-text-secondary">
                <DollarSign className="h-4 w-4 text-status-info" />
                估算成本
              </span>
              <span className="font-mono text-text-primary">{formatMoney({ amount: String(totalCost), currency })}</span>
            </div>
          </div>
        </section>

        <section className="card p-5">
          <h2 className="text-xl font-semibold text-text-primary">明细</h2>
          {items.length === 0 ? (
            <p className="mt-4 rounded-[18px] border border-dashed border-border bg-white/45 px-4 py-6 text-center text-sm text-text-tertiary">
              暂无明细
            </p>
          ) : (
            <div className="mt-4 space-y-2.5">
              {items.map((item) => (
                <div className="rounded-[18px] border border-border/70 bg-white/50 px-4 py-3" key={`${item.provider_id}:${item.capability_id}:${item.model_id ?? "all"}`}>
                  <div className="flex items-center justify-between gap-3">
                    <span className="min-w-0 truncate font-medium text-text-primary">{item.provider_id}</span>
                    <span className="font-mono text-sm text-text-primary">{item.calls.toLocaleString("zh-CN")}</span>
                  </div>
                  <p className="mt-1 truncate text-xs text-text-tertiary">
                    {item.capability_id} · {item.model_id ?? "全部模型"} · {formatRate(item.success_rate)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>
      </aside>
    </div>
  );
}
