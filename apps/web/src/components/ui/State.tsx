import type { ComponentType, ReactNode } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { isApiError } from "../../api/client";

type IconComponent = ComponentType<{ className?: string }>;

/**
 * Inline loading row (default) — a compact `stateBox` with a spinner + label.
 * Pass `block` to center it inside a min-height panel (page/section loaders).
 */
export function LoadingState({ label = "加载中", block = false }: { label?: string; block?: boolean }) {
  const box = (
    <div className="stateBox muted">
      <Loader2 size={16} className="spin" />
      <span>{label}</span>
    </div>
  );
  if (!block) return box;
  return <div className="grid min-h-[220px] place-items-center">{box}</div>;
}

/**
 * Empty-state placeholder.
 * - Default: compact `stateBox` (inline lists/panels).
 * - With `icon`: the centered dashed-box variant (page/grid empties) with an
 *   optional `action` (a CTA button/link) rendered beneath the copy.
 */
export function EmptyState({
  title,
  detail,
  icon: Icon,
  action,
}: {
  title: string;
  detail?: string;
  icon?: IconComponent;
  action?: ReactNode;
}) {
  if (Icon || action) {
    return (
      <div className="rounded-[24px] border border-dashed border-border bg-white/55 p-8 text-center">
        {Icon ? <Icon className="mx-auto h-8 w-8 text-text-tertiary" /> : null}
        <p className={`text-sm font-medium text-text-primary ${Icon ? "mt-3" : ""}`}>{title}</p>
        {detail ? <p className="mt-1 text-xs text-text-secondary">{detail}</p> : null}
        {action ? <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div> : null}
      </div>
    );
  }
  return (
    <div className="stateBox">
      <strong>{title}</strong>
      {detail ? <span>{detail}</span> : null}
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "未知错误";
  const requestId = isApiError(error) ? error.requestId : undefined;
  return (
    <div className="stateBox danger">
      <AlertTriangle size={16} />
      <div>
        <strong>{message}</strong>
        {requestId ? <span>request_id: {requestId}</span> : null}
      </div>
    </div>
  );
}
