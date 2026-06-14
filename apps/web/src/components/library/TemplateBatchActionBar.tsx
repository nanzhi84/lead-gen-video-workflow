import { Loader2, RefreshCw, Tag, Trash2 } from "lucide-react";

type TemplateBatchActionBarProps = {
  selectedCount: number;
  isStabilizing: boolean;
  onStabilize: () => void;
  onClear: () => void;
};

export function TemplateBatchActionBar({
  selectedCount,
  isStabilizing,
  onStabilize,
  onClear,
}: TemplateBatchActionBarProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border/80 bg-white/65 p-3">
      <span className="text-sm text-text-secondary">已选择 {selectedCount} 个素材</span>
      <div className="flex flex-wrap gap-2">
        <button className="btn-secondary min-h-9 px-3" type="button" disabled={selectedCount === 0 || isStabilizing} onClick={onStabilize}>
          {isStabilizing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          <span>{isStabilizing ? "增稳中" : "批量增稳"}</span>
        </button>
        <button className="btn-secondary min-h-9 px-3" type="button" disabled title="待接入（依赖 M6d）">
          <Tag className="h-4 w-4" />
          <span>改场景/标签</span>
        </button>
        <button className="btn-secondary min-h-9 px-3" type="button" disabled title="后端暂无素材删除 API">
          <Trash2 className="h-4 w-4" />
          <span>批量删除</span>
        </button>
        <button className="btn-ghost min-h-9 px-3" type="button" onClick={onClear}>
          清空选择
        </button>
      </div>
    </div>
  );
}
