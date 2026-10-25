import { useEffect, useId, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

interface ModalProps { open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }

/** Native <dialog>: focus trap, Esc to close, and focus return come from the platform. */
export function Modal({ open, title, onClose, children, footer }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className="modal" aria-labelledby={titleId} onClose={onClose} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      {open && (<>
        <header><h2 id={titleId}>{title}</h2><button className="btn icon" aria-label="Close dialog" onClick={onClose}><X size={16} aria-hidden /></button></header>
        <div className="body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </>)}
    </dialog>
  );
}

export function ConfirmDialog({ open, title, children, confirmLabel, busy, onConfirm, onCancel }: { open: boolean; title: string; children: ReactNode; confirmLabel: string; busy: boolean; onConfirm: () => void; onCancel: () => void }) {
  return (
    <Modal open={open} title={title} onClose={() => { if (!busy) onCancel(); }} footer={<>
      <button className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
      <button className="btn danger solid" onClick={onConfirm} disabled={busy}>{busy ? 'Working…' : confirmLabel}</button>
    </>}>{children}</Modal>
  );
}
