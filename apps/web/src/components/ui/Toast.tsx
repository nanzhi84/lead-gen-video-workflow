import { AlertCircle, CheckCircle, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ApiError } from "../../api/client";

export type ToastType = "success" | "error" | "warning" | "info";

export type Toast = {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  requestId?: string;
  duration?: number;
};

type ToastContextValue = {
  push: (toast: Omit<Toast, "id">) => void;
  success: (title: unknown, message?: unknown) => void;
  error: (title: unknown, message?: unknown) => void;
  warning: (title: unknown, message?: unknown) => void;
  info: (title: unknown, message?: unknown) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);
const TOAST_EVENT = "cutagent:toast";

export function formatToastText(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const messages = value.map((item) => formatToastText(item)).filter((item): item is string => Boolean(item));
    return messages.length > 0 ? messages.join("；") : undefined;
  }
  if (typeof value === "object") {
    const maybeMessage = value as { msg?: unknown; message?: unknown; detail?: unknown };
    return (
      formatToastText(maybeMessage.msg) ||
      formatToastText(maybeMessage.message) ||
      formatToastText(maybeMessage.detail) ||
      JSON.stringify(value)
    );
  }
  return String(value);
}

export function notifyError(error: ApiError) {
  window.dispatchEvent(
    new CustomEvent<Omit<Toast, "id">>(TOAST_EVENT, {
      detail: {
        type: "error",
        title: "请求失败",
        message: error.message,
        requestId: error.requestId,
      },
    }),
  );
}

const icons = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertCircle,
  info: Info,
};

const colors = {
  success: "border-status-success bg-status-success/10 text-status-success",
  error: "border-status-error bg-status-error/10 text-status-error",
  warning: "border-status-warning bg-status-warning/10 text-status-warning",
  info: "border-status-info bg-status-info/10 text-status-info",
};

function ToastItem({ toast, onRemove }: { toast: Toast; onRemove: (id: string) => void }) {
  const Icon = icons[toast.type];

  useEffect(() => {
    if (toast.duration === Infinity) return;
    const timer = window.setTimeout(() => onRemove(toast.id), toast.duration ?? 5000);
    return () => window.clearTimeout(timer);
  }, [onRemove, toast.duration, toast.id]);

  return (
    <div
      className={`flex items-start gap-3 rounded-xl border p-4 shadow-lg animate-in slide-in-from-right-full ${colors[toast.type]}`}
    >
      <Icon className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="min-w-0 flex-1">
        <h4 className="text-sm font-medium">{toast.title}</h4>
        {toast.message ? <p className="mt-1 text-sm opacity-80">{toast.message}</p> : null}
        {toast.requestId ? <p className="mt-1 font-mono text-xs opacity-70">request_id: {toast.requestId}</p> : null}
      </div>
      <button className="rounded p-1 transition-colors hover:bg-black/10" type="button" onClick={() => onRemove(toast.id)} aria-label="关闭提示">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

export function ToastContainer({ toasts, onRemove }: { toasts: Toast[]; onRemove: (id: string) => void }) {
  return (
    <div className="fixed right-4 top-4 z-[100] flex max-w-sm flex-col gap-2">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onRemove={onRemove} />
      ))}
    </div>
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback((toast: Omit<Toast, "id">) => {
    const id = crypto.randomUUID?.() ?? String(Date.now());
    setToasts((current) => [...current, { ...toast, id }].slice(-4));
  }, []);

  const addTyped = useCallback(
    (type: ToastType, title: unknown, message?: unknown) => {
      push({
        type,
        title: formatToastText(title) ?? "",
        message: formatToastText(message),
      });
    },
    [push],
  );

  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<Omit<Toast, "id">>).detail;
      if (detail) push({ ...detail, type: detail.type ?? "info" });
    };
    window.addEventListener(TOAST_EVENT, listener);
    return () => window.removeEventListener(TOAST_EVENT, listener);
  }, [push]);

  const value = useMemo(
    () => ({
      push,
      success: (title: unknown, message?: unknown) => addTyped("success", title, message),
      error: (title: unknown, message?: unknown) => addTyped("error", title, message),
      warning: (title: unknown, message?: unknown) => addTyped("warning", title, message),
      info: (title: unknown, message?: unknown) => addTyped("info", title, message),
    }),
    [addTyped, push],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastContainer toasts={toasts} onRemove={remove} />
    </ToastContext.Provider>
  );
}

export function useToast() {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider");
  return value;
}
