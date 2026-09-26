import clsx from "clsx";
import { Receipt } from "lucide-react";
import { useSettings, useTrades } from "../api";
import { Badge, Card, Empty, Loading, PageHeader, Stat } from "../components/ui";
import { price, rupees } from "../format";

export default function Trades() {
  const trades = useTrades();
  const settings = useSettings();
  const inr = settings.data?.usdt_inr ?? 88;
  const list = [...(trades.data ?? [])].sort((a, b) => b.opened_at.localeCompare(a.opened_at));
  const closed = list.filter((t) => t.pnl != null);
  const pnl = closed.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const wins = closed.filter((t) => (t.pnl ?? 0) > 0).length;

  return (
    <>
      <PageHeader title="Trades" subtitle="Every trade the agent made, with the news and checks behind it. Profit is shown in USDT and rupees." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Trades" value={list.length} />
        <Stat label="Open now" value={list.length - closed.length} />
        <Stat label="Won" value={closed.length ? `${wins}/${closed.length}` : "—"} />
        <Stat label="Total profit" value={closed.length ? rupees(pnl * inr) : "—"} tone={pnl >= 0 ? "text-up" : "text-down"} sub={closed.length ? `${pnl.toFixed(2)} USDT` : undefined} />
      </div>
      <Card title="Trade log" className="mt-4" pad={false}>
        {trades.isLoading ? <Loading /> : list.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wider text-ink-3">
                <tr className="border-b border-line">
                  {["Opened", "Coin", "Entry", "Stop", "Exit", "Profit", "Why closed", "News behind it"].map((h) => <th key={h} className="px-4 py-2.5 font-medium first:pl-5">{h}</th>)}
                </tr>
              </thead>
              <tbody className="num">
                {list.map((t) => (
                  <tr key={t.trade_id} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-2.5 pl-5 text-xs text-ink-3">{t.opened_at.slice(0, 16).replace("T", " ")}</td>
                    <td className="px-4 font-semibold">{t.symbol} <Badge tone="info">{t.action}</Badge></td>
                    <td className="px-4">{price(t.entry_price)}</td>
                    <td className="px-4 text-ink-3">{price(t.stop_price)}</td>
                    <td className="px-4">{t.exit_price == null ? <Badge tone="warn">open</Badge> : price(t.exit_price)}</td>
                    <td className={clsx("px-4", (t.pnl ?? 0) >= 0 ? "text-up" : "text-down")}>{t.pnl == null ? "—" : rupees(t.pnl * inr)}</td>
                    <td className="px-4 text-xs text-ink-3">{t.exit_reason?.replace("_", " ") ?? ""}</td>
                    <td className="max-w-xs truncate px-4 text-xs text-ink-2">{t.snapshot?.news?.headline ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty icon={<Receipt className="size-8" />} title="No trades yet">The agent only buys when news, price and risk all agree, so days without trades are normal.</Empty>}
      </Card>
    </>
  );
}
