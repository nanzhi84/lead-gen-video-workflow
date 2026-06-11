import { Loader2, Plus, Trash2 } from "lucide-react";
import type { PublishBatch } from "../../api/client";
import { TimeText } from "../TimeText";
import { StatusPill } from "../ui/StatusPill";

type RecentBatchesSidebarProps = {
  batches: PublishBatch[];
  activeBatchId?: string | null;
  isLoading?: boolean;
  onSelect: (batchId: string) => void;
  onDelete: (batch: PublishBatch) => void;
  onNew: () => void;
};

export function RecentBatchesSidebar({
  batches,
  activeBatchId,
  isLoading = false,
  onSelect,
  onDelete,
  onNew,
}: RecentBatchesSidebarProps) {
  return (
    <aside className="card grid content-start gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-text-primary">最近批次</h2>
          <p className="mt-1 text-sm text-text-secondary">切换草稿、复核发布结果。</p>
        </div>
        <button className="icon-button" type="button" onClick={onNew} title="新建批次">
          <Plus className="h-4 w-4" />
        </button>
      </div>
      {isLoading ? (
        <p className="flex items-center gap-2 text-sm text-text-secondary">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载批次
        </p>
      ) : null}
      <div className="grid max-h-[680px] gap-2 overflow-y-auto pr-1">
        {batches.map((batch) => (
          <div
            key={batch.id}
            className={`rounded-2xl border p-3 transition ${
              activeBatchId === batch.id
                ? "border-accent/30 bg-accent/10"
                : "border-border/75 bg-white/55 hover:bg-white/80"
            }`}
          >
            <button className="grid w-full gap-2 text-left" type="button" onClick={() => onSelect(batch.id)}>
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-mono text-xs text-text-tertiary">{batch.id.slice(0, 12)}</span>
                <StatusPill status={batch.status} />
              </div>
              <div className="flex items-center justify-between gap-2 text-xs text-text-secondary">
                <span>{batch.items?.length ?? 0} 条草稿</span>
                <TimeText value={batch.updated_at ?? batch.created_at} />
              </div>
            </button>
            <div className="mt-2 flex justify-end border-t border-border/60 pt-2">
              <button
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-text-tertiary hover:bg-status-error/10 hover:text-status-error"
                type="button"
                onClick={() => onDelete(batch)}
              >
                <Trash2 className="h-3.5 w-3.5" />
                删除
              </button>
            </div>
          </div>
        ))}
        {!isLoading && batches.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border/80 bg-white/50 p-4 text-center text-sm text-text-secondary">
            暂无发布批次
          </div>
        ) : null}
      </div>
    </aside>
  );
}
