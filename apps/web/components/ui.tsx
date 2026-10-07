// Spec: /ui/design-system.md (Components)
"use client";

import { ChevronDown, ChevronRight, Loader2, X } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import type { Tone } from "@/lib/format";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

type BtnVariant = "primary" | "secondary" | "ghost" | "danger";
export function Button({
  children, variant = "secondary", loading, className, ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; loading?: boolean }) {
  const styles: Record<BtnVariant, string> = {
    primary: "bg-accent text-on-accent hover:brightness-95 active:brightness-90",
    secondary: "bg-panel border-[1.5px] border-accent text-accent hover:bg-accent-soft",
    ghost: "text-accent hover:bg-accent-soft",
    danger: "bg-bad-soft border-[1.5px] border-bad text-bad hover:brightness-95",
  };
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={cx("inline-flex min-h-10 items-center justify-center gap-1.5 rounded-full px-4 py-2 text-sm font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed", styles[variant], className)}
    >
      {loading && <Loader2 size={14} className="animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ children, className, title, actions }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode }) {
  return (
    <section className={cx("rounded-2xl border border-line bg-panel shadow-[var(--shadow)]", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-line px-5 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

const toneCls: Record<Tone, string> = {
  ok: "bg-ok-soft text-ok", warn: "bg-warn-soft text-warn", bad: "bg-bad-soft text-bad", info: "bg-info-soft text-info",
  neutral: "bg-neutral-soft text-muted", accent: "bg-accent-soft text-accent",
};
export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: Tone; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", toneCls[tone], className)}>{children}</span>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={cx("px-4 py-2.5 text-sm -mb-px border-b-[3px] font-medium", value === t.id ? "border-accent text-accent" : "border-transparent text-muted hover:text-fg")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

const inputCls = "w-full min-h-10 rounded-[10px] border-[1.5px] border-line bg-panel px-3 py-2 text-sm outline-none focus:border-accent";
export const Input = (p: React.InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(inputCls, p.className)} />;
export const Textarea = (p: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cx(inputCls, "min-h-20", p.className)} />;
export const Select = (p: React.SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(inputCls, p.className)} />;

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string | null; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-muted">{label}</span>
      {children}
      {error ? <span className="block text-xs text-bad">{error}</span> : hint ? <span className="block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-line bg-panel px-5 py-4 shadow-[var(--shadow)]">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-2xl border-[1.5px] border-dashed border-line bg-panel p-10 text-center">
      <div className="font-medium">{title}</div>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export const Spinner = ({ label }: { label?: string }) => (
  <div className="flex items-center gap-2 text-sm text-muted"><Loader2 size={16} className="animate-spin" />{label}</div>
);

export function JsonView({ value, collapsed = true, label = "JSON" }: { value: unknown; collapsed?: boolean; label?: string }) {
  const [open, setOpen] = useState(!collapsed);
  return (
    <div className="text-xs">
      <button className="inline-flex items-center gap-1 text-muted hover:text-fg" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}{label}
      </button>
      {open && <pre className="mono mt-1 max-h-72 overflow-auto rounded-lg bg-neutral-soft p-2 whitespace-pre-wrap break-all">{JSON.stringify(value, null, 2)}</pre>}
    </div>
  );
}

export function Modal({ open, title, onClose, children, footer }: { open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl border border-line bg-panel shadow-xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <h3 className="font-semibold">{title}</h3>
          <button onClick={onClose} aria-label="Close"><X size={16} /></button>
        </header>
        <div className="space-y-3 p-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ toasts
type ToastItem = { id: number; text: string; tone: Tone };
const ToastCtx = createContext<(text: string, tone?: Tone) => void>(() => undefined);
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string, tone: Tone = "neutral") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, tone }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed right-4 top-4 z-[60] space-y-2">
        {items.map((t) => (
          <div key={t.id} className={cx("max-w-sm rounded-lg border border-line px-3 py-2 text-sm shadow", toneCls[t.tone], "bg-panel")}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export { cx };
