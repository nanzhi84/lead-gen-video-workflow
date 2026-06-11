import { Modal as PortalModal, type ModalSize } from "./ui/Modal";

export function Modal({
  title,
  children,
  onClose,
  size,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  size?: ModalSize;
}) {
  return (
    <PortalModal isOpen onClose={onClose} title={title} size={size}>
      {children}
    </PortalModal>
  );
}
