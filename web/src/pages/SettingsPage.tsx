import clsx from "clsx";
import { Save, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useSaveSettings, useSettings, type Settings } from "../api";
import { Button, Card, ErrorNote, Loading, PageHeader } from "../components/ui";

const TRIGGERS = [
  { id: "engulfing", label: "Engulfing", help: "a big candle swallows the previous one" },
  { id: "wick", label: "Hammer / wick", help: "price dipped and was pushed back up" },
  { id: "breakout", label: "Breakout", help: "close above the recent high" },
];

function Field({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <div className="grid gap-2 border-b border-line py-4 last:border-0 sm:grid-cols-[240px_1fr] sm:items-center">
      <div>
        <div className="text-sm font-medium">{label}</div>
        {help && <div className="text-xs text-ink-3">{help}</div>}
      </div>
      <div>{children}</div>
    </div>
  );
}

const input = "w-28 rounded-xl border border-line bg-panel-2 px-3 py-1.5 text-sm outline-none focus:border-accent/60";

export default function SettingsPage() {
  const q = useSettings();
  const save = useSaveSettings();
  const [s, setS] = useState<Settings | null>(null);
  const [coinInput, setCoinInput] = useState("");
  useEffect(() => { if (q.data) setS(q.data); }, [q.data]);
  if (!s) return <Loading />;
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setS({ ...s, [k]: v });

  return (
    <>
      <PageHeader title="Settings" subtitle="The agent's rules. Saved settings are used by the live system and the strategy lab."
        actions={<Button loading={save.isPending} onClick={() => save.mutate(s)}><Save className="size-4" /> {save.isSuccess ? "Saved ✓" : "Save"}</Button>} />
      {save.error && <div className="mb-4"><ErrorNote error={save.error} /></div>}

      <Card title="Risk">
        <Field label="Risk per trade" help="Money lost if a stop-loss is hit. Business rule: ₹200–300.">
          <div className="flex items-center gap-3">
            <input type="range" min={200} max={300} step={10} value={s.risk_per_trade_inr} onChange={(e) => set("risk_per_trade_inr", +e.target.value)} className="w-56 accent-[#3987e5]" />
            <span className="num font-semibold">₹{s.risk_per_trade_inr}</span>
          </div>
        </Field>
        <Field label="Stop-loss" help="Sell automatically if the price falls this far. Crypto needs 2% or more.">
          <div className="flex items-center gap-2">
            <input type="number" min={0.5} max={20} step={0.5} value={+(s.stop_loss_pct * 100).toFixed(2)} onChange={(e) => set("stop_loss_pct", +e.target.value / 100)} className={input} />
            <span className="text-sm text-ink-3">%</span>
          </div>
        </Field>
        <Field label="Rupees per USDT" help="Used to turn the ₹ risk into a USDT position size.">
          <input type="number" min={1} step={0.5} value={s.usdt_inr} onChange={(e) => set("usdt_inr", +e.target.value)} className={input} />
        </Field>
        <Field label="Market mood filter" help="No new buys while Bitcoin is below its 200-day average.">
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" checked={s.market_filter} onChange={(e) => set("market_filter", e.target.checked)} className="size-4 accent-[#3987e5]" /> On
          </label>
        </Field>
      </Card>

      <Card title="Price rules" className="mt-4">
        <Field label="Trend line" help="Buy only while the price is above its average of this many candles.">
          <input type="number" min={2} max={400} value={s.trend_window} onChange={(e) => set("trend_window", +e.target.value)} className={input} />
        </Field>
        <Field label="Breakout window" help="A breakout means closing above the high of this many previous candles.">
          <input type="number" min={1} max={100} value={s.breakout_window} onChange={(e) => set("breakout_window", +e.target.value)} className={input} />
        </Field>
        <Field label="Entry patterns" help="At least one must appear before the agent buys.">
          <div className="flex flex-wrap gap-2">
            {TRIGGERS.map((t) => {
              const on = s.triggers.includes(t.id);
              return (
                <button key={t.id} title={t.help} onClick={() => set("triggers", on ? s.triggers.filter((x) => x !== t.id) : [...s.triggers, t.id])}
                  className={clsx("rounded-xl border px-3 py-1.5 text-sm font-medium transition", on ? "border-accent/60 bg-accent/15" : "border-line text-ink-3")}>
                  {t.label}
                </button>
              );
            })}
          </div>
        </Field>
      </Card>

      <Card title="Coins" className="mt-4">
        <Field label="Coins to research and trade" help="Binance USDT pairs, e.g. BTCUSDT.">
          <div className="flex flex-wrap items-center gap-2">
            {s.coins.map((c) => (
              <span key={c} className="inline-flex items-center gap-1 rounded-xl border border-line bg-panel-2 py-1 pl-3 pr-1.5 text-sm font-medium">
                {c}
                <button onClick={() => set("coins", s.coins.filter((x) => x !== c))} className="rounded p-0.5 text-ink-3 hover:text-down" aria-label={`Remove ${c}`}><X className="size-3.5" /></button>
              </span>
            ))}
            <input value={coinInput} onChange={(e) => setCoinInput(e.target.value)} placeholder="add, e.g. XRPUSDT"
              onKeyDown={(e) => { if (e.key === "Enter" && coinInput.trim()) { set("coins", [...new Set([...s.coins, coinInput.trim().toUpperCase()])]); setCoinInput(""); } }}
              className="w-40 rounded-xl border border-line bg-panel-2 px-3 py-1.5 text-sm outline-none focus:border-accent/60" />
          </div>
        </Field>
      </Card>
    </>
  );
}
