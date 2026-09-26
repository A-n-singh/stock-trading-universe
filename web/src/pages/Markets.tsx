import clsx from "clsx";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useCandles, useMarkets, useSettings } from "../api";
import { CandleChart, Sparkline } from "../components/charts";
import { Badge, Card, ErrorNote, Loading, PageHeader, Segmented } from "../components/ui";
import { coin, pct, price, tone } from "../format";

const STOCKS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "AAPL", "NVDA"];

export default function Markets() {
  const settings = useSettings();
  const [params, setParams] = useSearchParams();
  const [market, setMarket] = useState<"crypto" | "stock">(params.get("market") === "stock" ? "stock" : "crypto");
  const [extra, setExtra] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [days, setDays] = useState(365);
  const base = market === "crypto" ? settings.data?.coins ?? [] : STOCKS;
  const symbols = [...new Set([...base, ...extra])];
  const selected = params.get("symbol") && symbols.includes(params.get("symbol")!) ? params.get("symbol")! : symbols[0] ?? "";
  const markets = useMarkets(market, symbols);
  const candles = useCandles(selected, market, days);
  const m = markets.data?.items.find((x) => x.symbol === selected);

  const pick = (sym: string) => setParams({ symbol: sym, market });
  const add = () => {
    const s = input.trim().toUpperCase();
    if (s) { setExtra((e) => [...e, s]); setInput(""); pick(s); }
  };

  return (
    <>
      <PageHeader
        title="Markets"
        subtitle="Candles with the trend line the agent uses. ▲ marks the days its price rules would agree to buy; a real trade also needs good news and a risk check."
        actions={<Segmented value={market} onChange={(v) => { setMarket(v); setParams({ market: v }); }}
          options={[{ value: "crypto", label: "Crypto · Binance" }, { value: "stock", label: "Stocks · Yahoo" }]} />}
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {symbols.map((s) => (
          <button key={s} onClick={() => pick(s)}
            className={clsx("rounded-xl border px-3 py-1.5 text-sm font-semibold transition",
              s === selected ? "border-accent/60 bg-accent/15 text-ink" : "border-line bg-panel text-ink-3 hover:text-ink-2")}>
            {market === "crypto" ? coin(s) : s}
          </button>
        ))}
        <div className="flex items-center gap-1 rounded-xl border border-line bg-panel pl-3">
          <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder={market === "crypto" ? "e.g. PEPEUSDT" : "e.g. TATAMOTORS.NS"}
            className="w-36 bg-transparent py-1.5 text-sm outline-none placeholder:text-ink-3" />
          <button onClick={add} className="rounded-r-xl px-2 py-1.5 text-ink-3 hover:text-ink" aria-label="Add symbol"><Plus className="size-4" /></button>
        </div>
      </div>

      <Card
        title={
          <span className="flex flex-wrap items-baseline gap-x-3">
            <span className="text-base text-ink">{selected}</span>
            {m && <span className="num text-lg font-semibold text-ink">{price(m.last)}</span>}
            {m && <span className={clsx("num text-sm", tone(m.change_1d))}>{pct(m.change_1d)} today</span>}
          </span>
        }
        action={<Segmented value={days} onChange={setDays} options={[
          { value: 90, label: "3M" }, { value: 180, label: "6M" }, { value: 365, label: "1Y" }, { value: 730, label: "2Y" }, { value: 3650, label: "All" },
        ]} />}
      >
        {candles.isLoading ? <Loading label="Loading candles…" /> : candles.error ? <ErrorNote error={candles.error} /> :
          candles.data && <CandleChart data={candles.data} />}
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-3">
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded bg-s1" /> {candles.data?.trend_window}-candle trend line</span>
          <span className="flex items-center gap-1.5"><span className="text-warn">▲</span> price rules say buy</span>
          <span>Hover the chart to read prices.</span>
        </div>
      </Card>

      <Card title="All symbols" className="mt-4" pad={false}>
        {markets.isLoading ? <Loading /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wider text-ink-3">
                <tr className="border-b border-line">
                  <th className="px-5 py-2.5 font-medium">Symbol</th><th className="px-3 font-medium">Price</th>
                  <th className="px-3 font-medium">1 day</th><th className="px-3 font-medium">30 days</th><th className="px-3 font-medium">1 year</th>
                  <th className="px-3 font-medium">Market mood</th><th className="px-3 font-medium">90 days</th>
                </tr>
              </thead>
              <tbody className="num">
                {markets.data?.items.map((x) => (
                  <tr key={x.symbol} onClick={() => pick(x.symbol)} className="cursor-pointer border-b border-line/60 last:border-0 hover:bg-white/3">
                    <td className="px-5 py-2.5 font-semibold">{x.symbol}</td>
                    <td className="px-3">{price(x.last)}</td>
                    <td className={clsx("px-3", tone(x.change_1d))}>{pct(x.change_1d)}</td>
                    <td className={clsx("px-3", tone(x.change_30d))}>{pct(x.change_30d)}</td>
                    <td className={clsx("px-3", tone(x.change_1y))}>{pct(x.change_1y)}</td>
                    <td className="px-3">{x.mood ? <Badge tone={x.mood === "rising" ? "up" : "down"}>{x.mood === "rising" ? "above" : "below"} 200-day avg</Badge> : "—"}</td>
                    <td className="px-3 py-1"><Sparkline values={x.spark} up={(x.change_30d ?? 0) >= 0} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {Object.entries(markets.data?.errors ?? {}).map(([s, e]) => (
              <div key={s} className="border-t border-line px-5 py-2 text-xs text-down">{s}: {e}</div>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
