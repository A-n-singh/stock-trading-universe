import clsx from "clsx";
import { CheckCircle2, FlaskConical, XCircle } from "lucide-react";
import { useState } from "react";
import { useApplyBest, useBacktest, useSettings, type BacktestRow } from "../api";
import { ProfitChart } from "../components/charts";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, Segmented, Stat } from "../components/ui";
import { r as fmtR, rupees } from "../format";

const label = (s: BacktestRow["setting"]) =>
  `trend ${s.trend_window} · breakout ${s.breakout_window} · ${s.triggers.join("+")} · stop ${(s.stop_loss_pct * 100).toFixed(1)}%`;

export default function Lab() {
  const settings = useSettings();
  const bt = useBacktest();
  const apply = useApplyBest();
  const [holdout, setHoldout] = useState(365);
  const [minTrades, setMinTrades] = useState(30);
  const [filter, setFilter] = useState(true);
  const [fair, setFair] = useState(true);
  const [shorts, setShorts] = useState(false);
  const res = bt.data;
  const risk = res?.risk_inr ?? settings.data?.risk_per_trade_inr ?? 250;

  const run = () => settings.data && bt.mutate({ symbols: settings.data.coins, holdout_days: holdout, min_trades: minTrades, market_filter: filter || shorts, fair_exam: fair, shorts });

  return (
    <>
      <PageHeader
        title="Strategy lab"
        subtitle="Tests 525 combinations of trend line, breakout window, entry patterns and stop-loss on your coins. The most recent period stays hidden while searching; the top 5 then sit an exam on it. A setting is used only if it still makes money there, or (fair exam) if the coins fell and it lost far less than simply holding them."
      />

      <Card>
        <div className="flex flex-wrap items-end gap-6">
          <label className="text-xs font-medium text-ink-3">Hide the last
            <div className="mt-1.5"><Segmented value={holdout} onChange={setHoldout} options={[90, 180, 365, 730].map((d) => ({ value: d, label: `${d} d` }))} /></div>
          </label>
          <label className="text-xs font-medium text-ink-3">Minimum practice trades
            <div className="mt-1.5"><Segmented value={minTrades} onChange={setMinTrades} options={[10, 30, 50, 100].map((d) => ({ value: d, label: String(d) }))} /></div>
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" checked={filter} disabled={shorts} onChange={(e) => setFilter(e.target.checked)} className="size-4 accent-[#3987e5]" />
            Market mood filter <span className="text-xs text-ink-3">(buy only while Bitcoin is above its 200-day average)</span>
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" checked={fair} onChange={(e) => setFair(e.target.checked)} className="size-4 accent-[#3987e5]" />
            Fair exam <span className="text-xs text-ink-3">(in a falling market, also pass if it lost at most ¼ of what holding the coins lost)</span>
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" checked={shorts} onChange={(e) => { setShorts(e.target.checked); if (e.target.checked) setFilter(true); }} className="size-4 accent-[#3987e5]" />
            Short selling <span className="text-xs text-ink-3">(also sell first and buy back lower while Bitcoin is below its average)</span>
          </label>
          <Button className="ml-auto" loading={bt.isPending} onClick={run}><FlaskConical className="size-4" /> {bt.isPending ? "Testing… (20–60 s)" : "Run the search"}</Button>
        </div>
        <div className="mt-3 text-xs text-ink-3">Coins: {settings.data?.coins.join(", ")} · results in R, where 1 R = one stop-loss hit = ₹{risk}</div>
      </Card>

      {bt.error && <div className="mt-4"><ErrorNote error={bt.error} /></div>}

      {!res && !bt.isPending && <Card className="mt-4"><Empty icon={<FlaskConical className="size-8" />} title="No results yet">Press <b>Run the search</b>.</Empty></Card>}

      {res && (
        <>
          <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Settings tested" value={res.settings_tested} />
            <Stat label="Profitable in practice" value={res.settings_eligible} />
            <Stat label="Passed hidden exam" value={res.rows.filter((x) => x.passed && x.rank !== "current").length} />
            <Stat label="Decision" value={res.chosen ? "Switch" : "Keep"} tone={res.chosen ? "text-up" : ""} sub={res.chosen ? "a new setting passed" : "stay with current settings"} />
          </div>
          <div className="mt-2 text-xs text-ink-3">
            Practice {res.practice_period[0].slice(0, 10)} → {res.practice_period[1].slice(0, 10)} · hidden {res.exam_period[0].slice(0, 10)} → {res.exam_period[1].slice(0, 10)}
            {Object.keys(res.hold_returns).length > 0 && (
              <> · the coins themselves in the hidden period: {Object.entries(res.hold_returns).map(([sym, r]) => (
                <span key={sym} className={clsx("num mr-2", r >= 0 ? "text-up" : "text-down")}>{sym.replace("USDT", "")} {(r * 100).toFixed(0)}%</span>
              ))}</>
            )}
          </div>

          <Card title="Results" className="mt-4" pad={false}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wider text-ink-3">
                  <tr className="border-b border-line">
                    <th className="px-5 py-2.5 font-medium">Rank</th><th className="px-3 font-medium">Exam</th>
                    <th className="px-3 font-medium">Hidden period</th><th className="px-3 font-medium">Just holding</th><th className="px-3 font-medium">Practice</th>
                    <th className="px-3 font-medium">Setting</th><th className="px-3 font-medium">Why</th>
                  </tr>
                </thead>
                <tbody className="num">
                  {res.rows.map((row) => (
                    <tr key={row.rank} className={clsx("border-b border-line/60 last:border-0", row.rank === "current" && "bg-white/3")}>
                      <td className="px-5 py-3 font-semibold">{row.rank}</td>
                      <td className="px-3">{row.passed ? <Badge tone="up"><CheckCircle2 className="size-3" /> {row.pass_kind === "beat_hold" ? "pass (fair)" : "pass"}</Badge> : <Badge tone="down"><XCircle className="size-3" /> fail</Badge>}</td>
                      <td className="px-3">
                        <div className={clsx("whitespace-nowrap font-semibold", row.exam.total_r >= 0 ? "text-up" : "text-down")}>
                          {fmtR(row.exam.total_r)} <span className="font-normal">{rupees(row.exam.total_r * risk)}</span>
                        </div>
                        <div className="whitespace-nowrap text-xs text-ink-3">{row.exam.trades} trades · {(row.exam.win_rate * 100).toFixed(0)}% won</div>
                      </td>
                      <td className="px-3">
                        {row.hold_r == null ? "—" : (
                          <div className={clsx("whitespace-nowrap", row.hold_r >= 0 ? "text-up" : "text-down")}>
                            {fmtR(row.hold_r)} <span className="text-xs">{rupees(row.hold_r * risk)}</span>
                          </div>
                        )}
                      </td>
                      <td className="px-3">
                        <div className={clsx("whitespace-nowrap", row.practice.total_r >= 0 ? "text-up" : "text-down")}>{fmtR(row.practice.total_r)}</div>
                        <div className="whitespace-nowrap text-xs text-ink-3">{row.practice.trades} trades · {(row.practice.win_rate * 100).toFixed(0)}% won</div>
                      </td>
                      <td className="min-w-56 px-3 text-xs text-ink-2">{label(row.setting)}</td>
                      <td className="px-3 text-xs text-ink-3">{row.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {res.curves.length > 0 && (
            <Card title="Running profit: practice, then the hidden period" className="mt-4">
              <ProfitChart curves={res.curves} cutoff={res.cutoff} />
              <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-3">
                {res.curves.map((c) => <span key={c.name} className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded" style={{ background: c.color }} /> {c.name}</span>)}
              </div>
            </Card>
          )}

          {res.chosen && (
            <Card className="mt-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-sm"><span className="font-semibold text-up">Winner:</span> {label(res.chosen)}</div>
                <Button loading={apply.isPending} onClick={() => apply.mutate(res.chosen!)}>{apply.isSuccess ? "Applied ✓" : "Use this setting"}</Button>
              </div>
            </Card>
          )}
        </>
      )}
    </>
  );
}
