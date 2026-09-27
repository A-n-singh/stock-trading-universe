import clsx from "clsx";
import { Receipt } from "lucide-react";
import { useMemo, useState } from "react";
import { useSettings, useTrades, type Trade } from "../api";
import { RunningTotalChart } from "../components/charts";
import { Badge, Card, Empty, Loading, PageHeader, Segmented, Stat } from "../components/ui";
import { price, rupees } from "../format";

const DAY = 86400;

function held(s: number) {
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 48 * 3600) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / DAY)} days`;
}

const pctText = (x: number | null) => (x == null ? "—" : `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)}%`);
const tone = (x: number | null | undefined) => (x == null ? "text-ink-3" : x >= 0 ? "text-up" : "text-down");
const isShort = (t: Trade) => t.action.toLowerCase() === "sell";

/** Running total of closed-trade profit, one point per day. */
function dailyCurve(closed: Trade[], inr: number) {
  const byDay = new Map<number, number>();
  for (const t of closed) {
    const day = Math.floor(new Date(t.closed_at!).getTime() / 1000 / DAY) * DAY;
    byDay.set(day, (byDay.get(day) ?? 0) + (t.pnl ?? 0) * inr);
  }
  const days = [...byDay.keys()].sort((a, b) => a - b);
  if (!days.length) return [];
  let total = 0;
  return [{ time: days[0] - DAY, value: 0 }, ...days.map((d) => ({ time: d, value: (total += byDay.get(d)!) }))];
}

export default function Trades() {
  const trades = useTrades();
  const settings = useSettings();
  const [show, setShow] = useState<"all" | "open" | "closed">("all");
  const inr = settings.data?.usdt_inr ?? 88;
  const list = useMemo(() => [...(trades.data ?? [])].sort((a, b) => b.opened_at.localeCompare(a.opened_at)), [trades.data]);
  const closed = list.filter((t) => t.pnl != null);
  const open = list.filter((t) => t.pnl == null);
  const realised = closed.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const unrealised = open.reduce((s, t) => s + (t.live_pnl ?? 0), 0);
  const inTrades = open.reduce((s, t) => s + t.invested, 0);
  const wins = closed.filter((t) => (t.pnl ?? 0) > 0).length;
  const curve = useMemo(() => dailyCurve(closed, inr), [closed, inr]);
  const desks = useMemo(() => {
    const m = new Map<string, { n: number; won: number; pnl: number }>();
    for (const t of closed) {
      const d = m.get(t.desk) ?? { n: 0, won: 0, pnl: 0 };
      d.n += 1; d.won += (t.pnl ?? 0) > 0 ? 1 : 0; d.pnl += t.pnl ?? 0;
      m.set(t.desk, d);
    }
    return [...m.entries()].sort((a, b) => b[1].pnl - a[1].pnl);
  }, [closed]);
  const rows = show === "open" ? open : show === "closed" ? closed : list;

  return (
    <>
      <PageHeader title="Trades" subtitle="Every buy and sell the agent made: money put in, profit or loss on each one (live for open trades), how long it was held, and the news and expert desk behind it. Paper money for now." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Profit, closed trades" value={closed.length ? rupees(realised * inr) : "—"} tone={closed.length ? tone(realised) : ""}
          sub={closed.length ? `${realised >= 0 ? "+" : ""}${realised.toFixed(2)} USDT · ${closed.length} trade(s)` : "no closed trades yet"} />
        <Stat label="Profit on open trades, now" value={open.length ? rupees(unrealised * inr) : "—"} tone={open.length ? tone(unrealised) : ""}
          sub={open.length ? `${open.length} open · not locked in until closed` : "no open trades"} />
        <Stat label="Won" value={closed.length ? `${wins}/${closed.length}` : "—"} sub={closed.length ? `${Math.round((wins / closed.length) * 100)}% of closed trades` : undefined} />
        <Stat label="Money in open trades" value={open.length ? `₹${(inTrades * inr).toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—"}
          sub={open.length ? `${inTrades.toFixed(0)} USDT` : undefined} />
      </div>

      {closed.length > 0 && (
        <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_360px]">
          <Card title="Running profit (closed trades, ₹)">
            <RunningTotalChart points={curve} />
          </Card>
          <Card title="Profit by expert desk" pad={false}>
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wider text-ink-3">
                <tr className="border-b border-line"><th className="px-5 py-2.5 font-medium">Desk</th><th className="px-3 font-medium">Won</th><th className="px-5 text-right font-medium">Profit</th></tr>
              </thead>
              <tbody className="num">
                {desks.map(([desk, d]) => (
                  <tr key={desk} className="border-b border-line/60 last:border-0">
                    <td className="px-5 py-2.5">{desk}</td>
                    <td className="px-3 text-ink-2">{d.won}/{d.n}</td>
                    <td className={clsx("px-5 text-right font-semibold", tone(d.pnl))}>{rupees(d.pnl * inr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="border-t border-line px-5 py-2.5 text-xs text-ink-3">Which desk's news led to trades that made money.</div>
          </Card>
        </div>
      )}

      <Card title="Trade log" className="mt-4" pad={false}
        action={<Segmented value={show} onChange={setShow} options={[
          { value: "all", label: `All ${list.length}` }, { value: "open", label: `Open ${open.length}` }, { value: "closed", label: `Closed ${closed.length}` },
        ]} />}>
        {trades.isLoading ? <Loading /> : rows.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wider text-ink-3">
                <tr className="border-b border-line">
                  {["Opened", "Coin", "Money in", "Entry → exit", "Profit", "Held", "Closed because", "News behind it"].map((h) =>
                    <th key={h} className="whitespace-nowrap px-4 py-2.5 font-medium first:pl-5">{h}</th>)}
                </tr>
              </thead>
              <tbody className="num">
                {rows.map((t) => {
                  const live = t.pnl == null;
                  const profit = live ? t.live_pnl : t.pnl;
                  return (
                    <tr key={t.trade_id} className="border-b border-line/60 align-top last:border-0">
                      <td className="whitespace-nowrap px-4 py-3 pl-5 text-xs text-ink-3">{t.opened_at.slice(0, 16).replace("T", " ")}</td>
                      <td className="whitespace-nowrap px-4 py-3 font-semibold">
                        {t.symbol.replace(/USDT$/, "")} <Badge tone={isShort(t) ? "down" : "info"}>{isShort(t) ? "short" : "long"}</Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        ₹{(t.invested * inr).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                        <div className="text-xs text-ink-3">{t.quantity} × {price(t.entry_price)}</div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        {price(t.entry_price)} → {live ? (t.live_price == null ? "—" : <span className="text-ink-2">{price(t.live_price)} <Badge tone="warn">now</Badge></span>) : price(t.exit_price)}
                        <div className="text-xs text-ink-3">stop-loss {price(t.stop_price)}</div>
                      </td>
                      <td className={clsx("whitespace-nowrap px-4 py-3 font-semibold", tone(profit))}>
                        {profit == null ? "—" : rupees(profit * inr)}
                        <div className="text-xs font-normal">{pctText(t.pct)}{t.r_multiple != null && <span className="text-ink-3"> · {t.r_multiple >= 0 ? "+" : "−"}{Math.abs(t.r_multiple).toFixed(1)} R</span>}{live && profit != null && <span className="text-ink-3"> · so far</span>}</div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-ink-2">{held(t.held_s)}{live && <div className="text-xs text-ink-3">still open</div>}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-ink-3">{live ? <Badge tone="warn">open</Badge> : t.exit_reason?.replaceAll("_", " ")}</td>
                      <td className="max-w-xs px-4 py-3 text-xs">
                        <div className="truncate text-ink-2" title={t.snapshot?.news?.headline ?? ""}>{t.snapshot?.news?.headline ?? "—"}</div>
                        <div className="text-ink-3">{t.desk} desk · {t.event_type} news</div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : <Empty icon={<Receipt className="size-8" />} title={show === "all" ? "No trades yet" : `No ${show} trades`}>
          The agent only trades when news, price and risk all agree, so days without trades are normal.
        </Empty>}
      </Card>
      <div className="mt-3 text-xs text-ink-3">1 R = one stop-loss hit = your ₹{settings.data?.risk_per_trade_inr ?? 250} risk per trade. Profit is after fees.</div>
    </>
  );
}
