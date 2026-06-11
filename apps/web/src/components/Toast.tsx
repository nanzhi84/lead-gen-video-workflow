import { X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ApiError } from "../api/client";

type ToastItem = {
  id: string;
  title: string;
  message: string;
  requestId?: string;
};

type ToastContextValue = {
  push: (toast: Omit<ToastItem, "id">) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);
const TOAST_EVENT = "cutagent:toast";

export function notifyError(error: ApiError) {
  window.dispatchEvent(
    new CustomEvent<Omit<ToastItem, "id">>(TOAST_EVENT, {
      detail: {
        title: "请求失败",
        message: error.message,
        requestId: error.requestId,
      },
    }),
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback((toast: Omit<ToastItem, "id">) => {
    const id = crypto.randomUUID?.() ?? String(Date.now());
    setItems((current) => [...current, { ...toast, id }].slice(-3));
    window.setTimeout(() => {
      setItems((current) => current.filter((item) => item.id !== id));
    }, 4800);
  }, []);

  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<Omit<ToastItem, "id">>).detail;
      if (detail) {
        push(detail);
      }
    };
    window.addEventListener(TOAST_EVENT, listener);
    return () => window.removeEventListener(TOAST_EVENT, listener);
  }, [push]);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toastRegion" aria-live="polite">
        {items.map((item) => (
          <div className="toast" key={item.id}>
            <div>
              <strong>{item.title}</strong>
              <p>{item.message}</p>
              {item.requestId ? <small>request_id: {item.requestId}</small> : null}
            </div>
            <button
              className="iconButton"
              type="button"
              onClick={() => setItems((current) => current.filter((next) => next.id !== item.id))}
              aria-label="关闭提示"
            >
              <X size={15} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const value = useContext(ToastContext);
  if (!value) {
    throw new Error("useToast must be used inside ToastProvider");
  }
  return value;
}
