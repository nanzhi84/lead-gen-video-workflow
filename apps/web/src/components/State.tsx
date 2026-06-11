import { AlertTriangle, Loader2 } from "lucide-react";
import { isApiError } from "../api/client";

export function LoadingState({ label = "加载中" }: { label?: string }) {
  return (
    <div className="stateBox muted">
      <Loader2 size={16} className="spin" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
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
