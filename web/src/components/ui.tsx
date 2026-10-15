import { AnimatePresence, motion } from "framer-motion";
import { Bot, Loader2, X } from "lucide-react";
import { type ReactNode, useEffect } from "react";
import { cn } from "../lib/utils";

export type User = { id: number; name: string; initials: string; color: string; kind: string; title?: string; email?: string; is_org_admin?: boolean };
export type Team = { id: number; name: string; short: string; color: string; handles?: string; lead_id?: number; autonomy?: string };

export const spring = { type: "spring", bounce: 0, duration: 0.45 } as const;

export function Avatar({ user, size = 22, className }: { user?: User | null; size?: number; className?: string }) {
  if (!user) return <span className={cn("inline-block rounded-full fill-2", className)} style={{ width: size, height: size }} />;
  const isAgent = user.kind === "agent";
  return (
    <span
      title={user.name}
      className={cn("inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white", className)}
      style={{ width: size, height: size, background: isAgent ? "#1D1D1F" : user.color, fontSize: Math.max(9, size * 0.4) }}
    >
      {isAgent ? <Bot size={size * 0.58} strokeWidth={2} aria-hidden /> : user.initials}
    </span>
  );
}

export function TeamDot({ color, className }: { color?: string; className?: string }) {
  return <span className={cn("inline-block h-2 w-2 shrink-0 rounded-[3px]", className)} style={{ background: color ?? "#8E8E93" }} />;
}

const TONES: Record<string, string> = {
  red: "bg-red/10 text-red",
  orange: "bg-orange/[0.14] text-orange",
  green: "bg-green/[0.14] text-green",
  purple: "bg-purple/[0.12] text-purple",
  blue: "bg-accent/10 text-accent-ink",
  teal: "bg-teal/[0.14] text-teal",
  gray: "fill text-fg2",
};

export function Badge({ tone = "gray", children, className }: { tone?: keyof typeof TONES; children: ReactNode; className?: string }) {
  return <span className={cn("badge", TONES[tone], className)}>{children}</span>;
}

export function Segmented<T extends string>({ value, onChange, options, label, size = "md" }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[]; label: string; size?: "sm" | "md";
}) {
  return (
    <div role="tablist" aria-label={label} className="relative inline-flex flex-wrap gap-0.5 rounded-[10px] p-0.5 fill">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            role="tab"
            aria-selected={on}
            onClick={() => onChange(o.value)}
            className={cn("relative rounded-lg font-medium transition-colors", size === "sm" ? "h-7 px-2.5 text-[12.5px]" : "h-[30px] px-3.5 text-[13px]",
              on ? "text-fg" : "text-fg2 hover:text-fg")}
          >
            {on && <motion.span layoutId={`seg-${label}`} transition={spring} className="absolute inset-0 rounded-lg shadow-[0_1px_3px_rgba(0,0,0,0.1)]" style={{ background: "var(--seg-on)" }} />}
            <span className="relative">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange?: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={cn("relative h-[26px] w-11 shrink-0 rounded-full transition-colors duration-200 disabled:opacity-60", checked ? "bg-[#34C759]" : "fill-2")}
    >
      <motion.span transition={spring} animate={{ x: checked ? 18 : 0 }}
        className="absolute left-0.5 top-0.5 h-[22px] w-[22px] rounded-full bg-white shadow-[0_2px_5px_rgba(0,0,0,0.22)]" />
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("animate-spin text-muted", className)} size={18} aria-label="Loading" />;
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
      {icon && <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-full fill text-muted">{icon}</div>}
      <p className="text-[17px] font-semibold">{title}</p>
      {children && <p className="max-w-sm text-[14px] text-muted">{children}</p>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return <div className="rounded-xl bg-red/10 px-4 py-3 text-[14px] text-red">{message}</div>;
}

/** Side sheet (non-modal on desktop, modal on phones). */
export function Sheet({ open, onClose, children, title }: { open: boolean; onClose: () => void; children: ReactNode; title: string }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          aria-label={title}
          initial={{ x: 24, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 24, opacity: 0 }}
          transition={spring}
          className="fixed inset-y-0 right-0 z-30 flex w-full max-w-[440px] flex-col border-l border-line/[0.07] bg-surface shadow-lift md:sticky md:top-0 md:h-screen md:shadow-none"
        >
          <button onClick={onClose} aria-label="Close" className="btn btn-ghost absolute right-3 top-3 z-10 h-8 w-8 px-0 text-muted">
            <X size={16} />
          </button>
          {children}
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

/** Centered modal dialog with dimmed backdrop. */
export function Dialog({ open, onClose, children, title, wide }: { open: boolean; onClose: () => void; children: ReactNode; title: string; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[10vh]">
          <motion.div className="absolute inset-0 bg-black/20 dark:bg-black/50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.div
            role="dialog"
            aria-label={title}
            initial={{ opacity: 0, scale: 0.97, y: -6, filter: "blur(6px)" }}
            animate={{ opacity: 1, scale: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, scale: 0.98, filter: "blur(4px)" }}
            transition={spring}
            className={cn("material relative w-full overflow-hidden rounded-3xl border border-line/[0.12] shadow-pop", wide ? "max-w-[760px]" : "max-w-[520px]")}
          >
            {children}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[28px] font-bold leading-tight tracking-[-0.022em]">{title}</h1>
        {subtitle && <p className="mt-0.5 text-[14px] text-muted">{subtitle}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </header>
  );
}
