import { AlertTriangle, Info, Loader2, ShieldAlert } from "lucide-react";
import { Modal } from "./Modal";

type ConfirmType = "danger" | "warning" | "info";

type ConfirmDialogProps = {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  message: string;
  consequences?: string[];
  confirmText?: string;
  cancelText?: string;
  type?: ConfirmType;
  isLoading?: boolean;
};

const iconByType = {
  danger: ShieldAlert,
  warning: AlertTriangle,
  info: Info,
};

const toneByType = {
  danger: "bg-status-error/10 text-status-error",
  warning: "bg-status-warning/10 text-status-warning",
  info: "bg-status-info/10 text-status-info",
};

export function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  consequences = [],
  confirmText = "确认",
  cancelText = "取消",
  type = "warning",
  isLoading = false,
}: ConfirmDialogProps) {
  const Icon = iconByType[type];
  const buttonClass = type === "danger" ? "btn-danger" : "btn-primary";

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="sm" showCloseButton={false}>
      <div className="grid gap-5 text-center">
        <div className={`mx-auto flex h-12 w-12 items-center justify-center rounded-full ${toneByType[type]}`}>
          <Icon className="h-6 w-6" />
        </div>
        <div className="grid gap-2">
          <h3 className="text-lg font-bold text-text-primary">{title}</h3>
          <p className="text-sm text-text-secondary">{message}</p>
        </div>
        {consequences.length > 0 ? (
          <div className="rounded-2xl border border-border/80 bg-white/65 p-3 text-left text-sm text-text-secondary">
            {consequences.map((item) => (
              <p key={item}>• {item}</p>
            ))}
          </div>
        ) : null}
        <div className="flex justify-center gap-3">
          <button className="btn-secondary" type="button" onClick={onClose} disabled={isLoading}>
            {cancelText}
          </button>
          <button className={buttonClass} type="button" onClick={() => void onConfirm()} disabled={isLoading}>
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            <span>{isLoading ? "处理中" : confirmText}</span>
          </button>
        </div>
      </div>
    </Modal>
  );
}
