import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import { X } from 'lucide-react';

type Tone = 'ok' | 'bad' | 'info';
interface Toast { id: number; tone: Tone; text: string }
const Ctx = createContext<(tone: Tone, text: string) => void>(() => {});
export const useToast = () => useContext(Ctx);

let nextId = 0;
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const dismiss = (id: number) => setItems((t) => t.filter((x) => x.id !== id));
  const push = useCallback((tone: Tone, text: string) => {
    const id = ++nextId;
    setItems((t) => [...t, { id, tone, text }]);
    setTimeout(() => dismiss(id), 5000);
  }, []);
  return (<Ctx.Provider value={push}>{children}
    <div className="toasts" role="status" aria-live="polite">
      {items.map((t) => <div key={t.id} className={`toast ${t.tone}`}><span>{t.text}</span><button className="btn icon" aria-label="Dismiss notification" onClick={() => dismiss(t.id)}><X size={14} aria-hidden /></button></div>)}
    </div></Ctx.Provider>);
}
