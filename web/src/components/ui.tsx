import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Card({ title, action, children, className, pad = true }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={clsx("rounded-2xl border border-line bg-panel", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <h2 className="text-sm font-semibold tracking-wide text-ink-2">{title}</h2>
          {action}
        </header>
      )}
      <div className={clsx(pad && "p-5")}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="rounded-2xl border border-line bg-panel px-5 py-4">
      <div className="text-xs font-medium uppercase tracking-wider text-ink-3">{label}</div>
      <div className={clsx("num mt-1.5 text-2xl font-semibold", tone)}>{value}</div>
      {sub && <div className="mt-1 text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

const badgeTones = {
  up: "bg-up/12 text-up ring-up/25",
  down: "bg-down/12 text-down ring-down/25",
  warn: "bg-warn/12 text-warn ring-warn/25",
  info: "bg-accent/12 text-accent ring-accent/25",
  muted: "bg-white/5 text-ink-2 ring-white/10",
};

export function Badge({ children, tone = "muted" }: { children: ReactNode; tone?: keyof typeof badgeTones }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", badgeTones[tone])}>
      {children}
    </span>
  );
}

export function Button({ children, loading, variant = "primary", className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & {
  loading?: boolean; variant?: "primary" | "ghost";
}) {
  return (
    <button
      {...rest}
      disabled={loading || rest.disabled}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" ? "bg-accent text-white hover:bg-accent/85" : "border border-line bg-panel-2 text-ink hover:bg-white/5",
        className,
      )}
    >
      {loading && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && <div className="text-ink-3">{icon}</div>}
      <div className="font-medium text-ink-2">{title}</div>
      {children && <div className="max-w-md text-sm text-ink-3">{children}</div>}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-5 py-10 text-sm text-ink-3">
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  return (
    <div className="rounded-xl border border-down/30 bg-down/10 px-4 py-3 text-sm text-down">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

export function Segmented<T extends string | number>({ options, value, onChange }: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-xl border border-line bg-panel-2 p-0.5">
      {options.map((o) => (
        <button
          key={String(o.value)}
          onClick={() => onChange(o.value)}
          className={clsx("rounded-[10px] px-3 py-1 text-xs font-semibold transition",
            o.value === value ? "bg-white/10 text-ink" : "text-ink-3 hover:text-ink-2")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Meter({ value }: { value: number }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-white/8">
        <div className="h-full rounded-full bg-accent" style={{ width: `${v * 100}%` }} />
      </div>
      <span className="num text-xs text-ink-2">{v.toFixed(2)}</span>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-ink-3">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
