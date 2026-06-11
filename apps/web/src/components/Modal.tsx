import { X } from "lucide-react";

export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="modalBackdrop" role="presentation" onMouseDown={onClose}>
      <section className="modalPanel" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <header className="modalHeader">
          <h2>{title}</h2>
          <button className="iconButton" type="button" onClick={onClose} aria-label="关闭">
            <X size={16} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
