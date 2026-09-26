import { Play, RefreshCw, Terminal } from "lucide-react";
import { useRunResearch, useSettings, useStatus, useTradeStep } from "../api";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, Stat } from "../components/ui";
import { ago, coin } from "../format";

const kindTone = (k: string) =>
  (k === "opened" ? "up" : k === "closed" ? "info" : k === "rejected" || k === "degraded" ? "down" : k === "watching" ? "warn" : "muted") as
    "up" | "info" | "down" | "warn" | "muted";

export default function Agent() {
  const status = useStatus();
  const settings = useSettings();
  const step = useTradeStep();
  const research = useRunResearch();
  const s = status.data ?? {};
  const inr = settings.data?.usdt_inr ?? 88;

  return (
    <>
      <PageHeader
        title="Live agent"
        subtitle="The fast loop. It reads the research snapshots and prices, and buys only when news, price and risk all agree. Paper money: 1,000 USDT to start."
        actions={
          <>
            <Button variant="ghost" loading={research.isPending} onClick={() => research.mutate()}><RefreshCw className="size-4" /> Run research</Button>
            <Button loading={step.isPending} onClick={() => step.mutate()}><Play className="size-4" /> Run one trading step</Button>
          </>
        }
      />
      {(step.error || research.error) && <div className="mb-4"><ErrorNote error={step.error || research.error} /></div>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Account" value={`${(s.equity_usdt ?? 0).toFixed(0)} USDT`} sub={`≈ ₹${((s.equity_usdt ?? 0) * inr).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`} />
        <Stat label="Cash" value={`${(s.cash_usdt ?? 0).toFixed(0)} USDT`} />
        <Stat label="Research cycles" value={s.research_cycles ?? 0} sub={`last ${ago(s.last_research_at)}`} />
        <Stat label="Trading steps" value={s.trade_ticks ?? 0} sub={`last ${ago(s.last_trade_tick_at)}`} />
      </div>

      {step.data && (
        <Card title="Result of the last step" className="mt-4" pad={false}>
          <ul className="divide-y divide-line">
            {step.data.events.map((e, i) => (
              <li key={i} className="flex flex-wrap items-center gap-3 px-5 py-2.5 text-sm">
                <span className="w-14 font-semibold">{coin(e.symbol)}</span>
                <Badge tone={kindTone(e.kind)}>{e.kind}</Badge>
                <span className="text-ink-2">{e.detail}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Open positions" pad={false}>
          {Object.keys(s.open_positions ?? {}).length ? (
            <ul className="divide-y divide-line">
              {Object.entries(s.open_positions ?? {}).map(([sym, q]) => (
                <li key={sym} className="flex justify-between px-5 py-2.5 text-sm"><span className="font-semibold">{sym}</span><span className="num">{q}</span></li>
              ))}
            </ul>
          ) : <Empty title="No open positions">The agent is in cash. It waits for news, price and risk to agree.</Empty>}
        </Card>
        <Card title="Recent activity" pad={false}>
          {s.last_events?.length ? (
            <ul className="max-h-96 divide-y divide-line overflow-auto font-mono text-xs">
              {[...s.last_events].reverse().map((e, i) => <li key={i} className="px-5 py-2 text-ink-2">{e}</li>)}
            </ul>
          ) : <Empty title="Nothing yet" />}
        </Card>
      </div>

      {!!s.errors?.length && (
        <Card title={`Problems (${s.errors.length})`} className="mt-4" pad={false}>
          <ul className="divide-y divide-line font-mono text-xs">
            {[...s.errors].reverse().map((e, i) => <li key={i} className="px-5 py-2 text-warn">{e}</li>)}
          </ul>
        </Card>
      )}

      <Card title={<span className="flex items-center gap-2"><Terminal className="size-4" /> Keep it running around the clock</span>} className="mt-4">
        <p className="text-sm text-ink-2">The buttons above run one step at a time. For non-stop paper trading, start this on a computer or small server; this page then shows what it is doing:</p>
        <pre className="mt-3 overflow-x-auto rounded-xl bg-bg px-4 py-3 font-mono text-xs text-ink-2">python -m trading_universe run{"\n"}python -m trading_universe run --broker binance-testnet   # fake money on Binance's testnet</pre>
      </Card>
    </>
  );
}
