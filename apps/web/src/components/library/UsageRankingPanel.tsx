import { BarChart3 } from "lucide-react";
import type { MaterialUsageRankingReport } from "../../api/client";
import { formatRelativeTime, shortId } from "../../lib/format";

export function UsageRankingPanel({
  report,
  isLoading,
  error,
}: {
  report?: MaterialUsageRankingReport;
  isLoading: boolean;
  error: unknown;
}) {
  const items = report?.items ?? [];
  return (
    <section className="grid gap-3 rounded-2xl border border-border/70 bg-white/55 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-semibold text-text-primary">使用排行</h3>
        </div>
        <span className="badge bg-white/70 text-text-secondary">{items.length} 条</span>
      </div>
      {isLoading ? <p className="text-sm text-text-secondary">排行加载中...</p> : null}
      {error ? <p className="text-sm text-status-error">使用排行加载失败：{String(error)}</p> : null}
      {!isLoading && !error && items.length === 0 ? <p className="text-sm text-text-secondary">暂无使用记录</p> : null}
      {items.length > 0 ? (
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {items.slice(0, 6).map((item, index) => (
            <div key={item.asset_id} className="grid gap-1 rounded-xl border border-border/60 bg-white/65 p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-sm font-semibold text-text-primary">
                  #{index + 1} {item.asset?.title ?? shortId(item.asset_id, 12)}
                </p>
                <span className="badge bg-accent/10 text-accent">{item.task_use_count} 次</span>
              </div>
              <p className="font-mono text-xs text-text-tertiary">{shortId(item.asset_id, 14)}</p>
              <p className="text-xs text-text-secondary">
                片段 {item.segment_use_count} · 最近 {formatRelativeTime(item.last_used_at)}
              </p>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
