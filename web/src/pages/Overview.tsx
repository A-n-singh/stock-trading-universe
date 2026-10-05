import { Play, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";
import { useMarkets, useRunResearch, useSettings, useSnapshots, useStatus, useTradeStep } from "../api";
import { Sparkline } from "../components/charts";
import { Badge, Button, Card, Empty, ErrorNote, Loading, Meter, PageHeader, Stat } from "../components/ui";
import { ago, coin, pct, price, tone } from "../format";

export default function Overview() {
  const settings = useSettings();
  const coins = settings.data?.coins ?? [];
  const markets = useMarkets(coins);
  const snaps = useSnapshots();
  const status = useStatus();
  const research = useRunResearch();
  const step = useTradeStep();
  const s = status.data ?? {};
  const inr = settings.data?.usdt_inr ?? 88;

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Your coins, what the research team thinks of them, and what the trading agent is doing. Paper money only."
        actions={
          <>
            <Button variant="ghost" loading={research.isPending} onClick={() => research.mutate()}>
              <RefreshCw className="size-4" /> Run research
            </Button>
            <Button loading={step.isPending} onClick={() => step.mutate()}>
              <Play className="size-4" /> Trading step
            </Button>
          </>
        }
      />
      {(research.error || step.error) && <div className="mb-4"><ErrorNote error={research.error || step.error} /></div>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Account" value={`${(s.equity_usdt ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 })} USDT`}
          sub={`≈ ₹${((s.equity_usdt ?? 0) * inr).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`} />
        <Stat label="Open positions" value={Object.keys(s.open_positions ?? {}).length} sub={s.broker ? `broker: ${s.broker}${s.shorts ? " · shorts on" : ""}` : "not started"} />
        <Stat
          label="Market mood"
          value={s.market_downtrend == null ? "—" : s.market_downtrend ? "Falling" : "Rising"}
          tone={s.market_downtrend == null ? "" : s.market_downtrend ? "text-down" : "text-up"}
          sub="Bitcoin vs its 200-day average"
        />
        <Stat label="Last research" value={ago(s.last_research_at)} sub={s.scorer ? `news read by: ${s.scorer}` : undefined} />
      </div>

      <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wider text-ink-3">Coins</h2>
      {markets.isLoading ? <Loading label="Loading prices…" /> : markets.error ? <ErrorNote error={markets.error} /> : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {markets.data?.items.map((m) => {
            const snap = snaps.data?.[m.symbol];
            const up = (m.change_30d ?? 0) >= 0;
            return (
              <Link key={m.symbol} to={`/markets?symbol=${m.symbol}`}
                className="group rounded-2xl border border-line bg-panel p-4 transition hover:border-accent/40 hover:bg-panel-2">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-sm font-semibold">{coin(m.symbol)}<span className="text-ink-3">/USDT</span></div>
                    <div className="num mt-1 text-xl font-semibold">{price(m.last)}</div>
                  </div>
                  <Sparkline values={m.spark} up={up} />
                </div>
                <div className="num mt-3 flex gap-4 text-xs">
                  <span className={tone(m.change_1d)}>1d {pct(m.change_1d)}</span>
                  <span className={tone(m.change_30d)}>30d {pct(m.change_30d)}</span>
                  <span className={tone(m.change_1y)}>1y {pct(m.change_1y)}</span>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
                  {m.mood && <Badge tone={m.mood === "rising" ? "up" : "down"}>{m.mood === "rising" ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />} {m.mood}</Badge>}
                  {snap ? (
                    <>
                      <Badge tone={snap.direction_bias === "bullish" ? "up" : snap.direction_bias === "bearish" ? "down" : "muted"}>research: {snap.direction_bias}</Badge>
                      {snap.risk_flags.map((f) => <Badge key={f} tone="warn">{f.replace("_", " ")}</Badge>)}
                    </>
                  ) : <span className="text-xs text-ink-3">no research yet</span>}
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <div className="mt-8 grid gap-4 lg:grid-cols-5">
        <Card title="Research snapshots" className="lg:col-span-3" pad={false}
          action={<Link to="/research" className="text-xs font-medium text-accent hover:underline">All news →</Link>}>
          {snaps.data && Object.keys(snaps.data).length ? (
            <ul className="divide-y divide-line">
              {Object.values(snaps.data).map((sn) => (
                <li key={sn.symbol} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3">
                  <span className="w-14 font-semibold">{coin(sn.symbol)}</span>
                  <Badge tone={sn.direction_bias === "bullish" ? "up" : sn.direction_bias === "bearish" ? "down" : "muted"}>{sn.direction_bias}</Badge>
                  <Meter value={sn.confidence} />
                  <span className="min-w-0 flex-1 truncate text-sm text-ink-2">{sn.news?.headline ?? "No recent news"}</span>
                  {sn.news?.actionable && <Badge tone="info">act on news</Badge>}
                </li>
              ))}
            </ul>
          ) : <Empty title="No research yet">Press <b>Run research</b> to collect news and write a snapshot for each coin.</Empty>}
        </Card>
        <Card title="Recent activity" className="lg:col-span-2" pad={false}>
          {s.last_events?.length ? (
            <ul className="max-h-80 divide-y divide-line overflow-auto">
              {[...s.last_events].reverse().slice(0, 15).map((e, i) => (
                <li key={i} className="px-5 py-2.5 text-sm">
                  <span className="num mr-2 text-xs text-ink-3">{e.slice(5, 16)}</span>
                  <span className="text-ink-2">{e.slice(17)}</span>
                </li>
              ))}
            </ul>
          ) : <Empty title="Nothing yet">Activity appears here once research or trading runs.</Empty>}
          {step.data && (
            <div className="border-t border-line px-5 py-3 text-xs text-ink-3">
              Last step: {step.data.events.map((e) => `${coin(e.symbol)} ${e.kind}`).join(" · ") || "no coins"}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
