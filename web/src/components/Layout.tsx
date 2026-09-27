import clsx from "clsx";
import {
  Activity, BookOpen, Bot, Brain, Network, CandlestickChart, FlaskConical, LayoutDashboard, LogOut, Menu, Newspaper, Receipt, Settings, X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth, useLogout, useStatus } from "../api";
import { ago } from "../format";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/markets", label: "Markets", icon: CandlestickChart },
  { to: "/research", label: "News & research", icon: Newspaper },
  { to: "/agents", label: "Agents", icon: Network },
  { to: "/agent", label: "Live agent", icon: Bot },
  { to: "/lab", label: "Strategy lab", icon: FlaskConical },
  { to: "/trades", label: "Trades", icon: Receipt },
  { to: "/memory", label: "Memory", icon: Brain },
  { to: "/settings", label: "Settings", icon: Settings },
  { to: "/roadmap", label: "Roadmap", icon: BookOpen },
];

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <div className="grid size-8 place-items-center rounded-lg bg-accent">
        <Activity className="size-4.5 text-white" strokeWidth={2.5} />
      </div>
      <div>
        <div className="text-sm font-semibold leading-tight">Trading Universe</div>
        <div className="text-[11px] leading-tight text-ink-3">crypto research & trading</div>
      </div>
    </div>
  );
}

function Nav({ onPick }: { onPick?: () => void }) {
  return (
    <nav className="mt-6 flex flex-col gap-0.5">
      {NAV.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          onClick={onPick}
          className={({ isActive }) =>
            clsx("flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition",
              isActive ? "bg-white/8 text-ink" : "text-ink-3 hover:bg-white/4 hover:text-ink-2")
          }
        >
          <Icon className="size-4" /> {label}
        </NavLink>
      ))}
    </nav>
  );
}

function LiveDot() {
  const { data } = useStatus();
  const last = data?.last_trade_tick_at || data?.last_research_at;
  const fresh = last && Date.now() - new Date(last).getTime() < 5 * 60_000;
  return (
    <div className="mx-2 mt-auto rounded-xl border border-line bg-panel-2 px-3 py-2.5 text-xs">
      <div className="flex items-center gap-2 font-medium text-ink-2">
        <span className={clsx("size-2 rounded-full", fresh ? "bg-up shadow-[0_0_8px] shadow-up" : "bg-ink-3")} />
        {fresh ? "Agent running" : "Agent idle"}
      </div>
      <div className="mt-0.5 text-ink-3">Paper money · last activity {ago(last)}</div>
      <LogoutButton />
    </div>
  );
}

function LogoutButton() {
  const auth = useAuth();
  const logout = useLogout();
  if (!auth.data?.required) return null;
  return (
    <button onClick={() => logout.mutate()} className="mt-2 flex items-center gap-1.5 text-ink-3 hover:text-ink-2">
      <LogOut className="size-3.5" /> Log out
    </button>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const current = NAV.find((n) => (n.to === "/" ? pathname === "/" : pathname.startsWith(n.to)));
  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-panel/60 p-4 lg:flex">
        <Brand />
        <Nav />
        <LiveDot />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-line bg-panel p-4">
            <div className="flex items-center justify-between">
              <Brand />
              <button onClick={() => setOpen(false)} className="rounded-lg p-1.5 text-ink-3 hover:bg-white/5" aria-label="Close menu">
                <X className="size-5" />
              </button>
            </div>
            <Nav onPick={() => setOpen(false)} />
            <LiveDot />
          </aside>
        </div>
      )}

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-bg/85 px-4 py-3 backdrop-blur lg:hidden">
          <button onClick={() => setOpen(true)} className="rounded-lg p-1.5 text-ink-2 hover:bg-white/5" aria-label="Open menu">
            <Menu className="size-5" />
          </button>
          <span className="text-sm font-semibold">{current?.label ?? "Trading Universe"}</span>
        </header>
        <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
      </div>
    </div>
  );
}
