import clsx from "clsx";
import { Brain as BrainIcon, History } from "lucide-react";
import { useBrain, type ScoreRow, type TimeMachineReport } from "../api";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, Stat } from "../components/ui";

const DESKS: Record<string, string> = {
  listings: "Listings", regulatory: "Regulation", security: "Hacks & security", macro: "Macro economy",
  flows: "Big buyers/sellers", tech: "Tech upgrades", social: "Social media", general: "General",
  trend: "Trend", momentum: "Momentum", patterns: "Candle patterns", events: "Event risk", mood: "Market mood", swings: "Wild swings",
};

const SECTIONS: { id: ScoreRow["section"]; title: string; help: string }[] = [
  { id: "news", title: "News & sentiment", help: "Each kind of news, by the desk that judged it" },
  { id: "price", title: "Price & technical", help: "Chart signals from the price desks" },
  { id: "risk", title: "Risk & portfolio", help: "Warnings from the risk desks" },
];

const pct = (x: number) => `${Math.round(x * 100)}%`;
const words = (s: string) => s.replaceAll("_", " ");

function Trust({ w, n }: { w: number; n: number }) {
  if (n < 10) return <Badge>learning ({n})</Badge>;
  if (w >= 1.05) return <Badge tone="up">trusted more ×{w.toFixed(2)}</Badge>;
  if (w <= 0.95) return <Badge tone="down">trusted less ×{w.toFixed(2)}</Badge>;
  return <Badge>no edge yet</Badge>;
}

function ScoreTable({ rows }: { rows: ScoreRow[] }) {
  if (!rows.length) return <Empty title="Nothing checked yet">Signals are checked 3 days after they appear.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase tracking-wider text-ink-3">
          <tr className="border-b border-line">
            {["Desk", "Signal", "Times", "Right", "Would be right anyway", "Edge", "Avg move after", "Trust"].map((h) =>
              <th key={h} className="whitespace-nowrap px-4 py-2.5 font-medium first:pl-5">{h}</th>)}
          </tr>
        </thead>
        <tbody className="num">
          {rows.map((r) => (
            <tr key={`${r.desk}:${r.kind}`} className="border-b border-line/60 last:border-0">
              <td className="whitespace-nowrap px-4 py-2.5 pl-5 font-medium">{DESKS[r.desk] ?? words(r.desk)}</td>
              <td className="whitespace-nowrap px-4 text-ink-2">{words(r.kind)}</td>
              <td className="px-4">{r.signals}</td>
              <td className="px-4">{pct(r.hit_rate)}</td>
              <td className="px-4 text-ink-3">{pct(r.base_rate)}</td>
              <td className={clsx("px-4 font-semibold", r.edge > 0.02 ? "text-up" : r.edge < -0.02 ? "text-down" : "text-ink-3")}>
                {r.edge >= 0 ? "+" : "−"}{Math.abs(Math.round(r.edge * 100))} pts
              </td>
              <td className={clsx("px-4", r.avg_move >= 0 ? "text-up" : "text-down")}>{r.avg_move >= 0 ? "+" : "−"}{Math.abs(r.avg_move * 100).toFixed(1)}%</td>
              <td className="whitespace-nowrap px-4"><Trust w={r.weight} n={r.signals} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TimeMachine({ r }: { r: TimeMachineReport }) {
  const e = r.exam_summary;
  return (
    <>
      <p className="text-sm text-ink-2">
        Replayed {r.period.start.slice(0, 10)} → {r.period.end.slice(0, 10)} day by day ({r.days.toLocaleString()} days,{" "}
        {r.news_items.toLocaleString()} news items, read by {r.scorer}). It learned until {r.period.cutoff.slice(0, 10)}, then sat an
        exam on the rest without learning.
      </p>
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Exam signals" value={e.signals.toLocaleString()} />
        <Stat label="Right in the exam" value={pct(e.hit_rate)} sub={`would be right anyway: ${pct(e.base_rate)}`} />
        <Stat label="Edge" value={`${e.edge >= 0 ? "+" : "−"}${Math.abs(Math.round(e.edge * 100))} pts`} tone={e.edge > 0 ? "text-up" : "text-down"}
          sub="right minus right-anyway" />
        <Stat label="Using what it learned" value={pct(e.weighted_hit_rate)} sub="right, counting trusted signals more" />
      </div>
      {r.trades && (
        <div className="mt-3 rounded-xl border border-line bg-panel-2 px-4 py-3 text-sm">
          Pretend trades in the exam: <b>{r.trades.trades}</b> trades, {r.trades.won} won,{" "}
          <b className={r.trades.total_r >= 0 ? "text-up" : "text-down"}>{r.trades.total_r >= 0 ? "+" : "−"}{Math.abs(r.trades.total_r).toFixed(1)} R</b>{" "}
          (≈ ₹{Math.round(r.trades.profit_inr).toLocaleString("en-IN")}); just holding the coins: {r.trades.hold_r >= 0 ? "+" : "−"}{Math.abs(r.trades.hold_r).toFixed(1)} R.
        </div>
      )}
      <h3 className="mb-2 mt-5 text-sm font-semibold text-ink-2">How each kind of signal did in the exam</h3>
      <Card pad={false}><ScoreTable rows={r.exam} /></Card>
    </>
  );
}

export default function Brain() {
  const q = useBrain();
  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) return <ErrorNote error={q.error ?? "no data"} />;
  const { summary, scorecard, time_machine } = q.data;
  const learned = scorecard.filter((r) => r.signals >= 10);
  const best = [...learned].sort((a, b) => b.edge - a.edge)[0];
  const worst = [...learned].sort((a, b) => a.edge - b.edge)[0];

  return (
    <>
      <PageHeader title="Brain" subtitle="What the research team has learned about what really moves prices. Every news item, chart signal and risk warning is written down; 1 and 3 days later the brain checks what the price did. Signals that keep being right are trusted more, ones that keep being wrong less." />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Signals written down" value={summary.signals.toLocaleString()} />
        <Stat label="Checked against the price" value={summary.settled.toLocaleString()} sub={`${summary.waiting.toLocaleString()} still within their 3 days`} />
        <Stat label="Best so far" value={best ? (DESKS[best.desk] ?? best.desk) : "—"} sub={best ? `${words(best.kind)}: ${best.edge >= 0 ? "+" : "−"}${Math.abs(Math.round(best.edge * 100))} pts edge` : "needs 10+ checked signals"} />
        <Stat label="Weakest so far" value={worst ? (DESKS[worst.desk] ?? worst.desk) : "—"} sub={worst ? `${words(worst.kind)}: ${worst.edge >= 0 ? "+" : "−"}${Math.abs(Math.round(worst.edge * 100))} pts edge` : "needs 10+ checked signals"} />
      </div>

      <div className="mt-3 text-xs text-ink-3">
        <b>Right</b> = the price moved the way the signal said within 3 days. <b>Would be right anyway</b> = how often the price moved that way regardless
        (so a "buy" signal in a rising market isn't mistaken for skill). <b>Edge</b> = the difference. Trust moves slowly until a signal has been checked dozens of times.
      </div>

      {SECTIONS.map((s) => (
        <Card key={s.id} title={<span>{s.title} <span className="font-normal text-ink-3">· {s.help}</span></span>} className="mt-4" pad={false}>
          <ScoreTable rows={scorecard.filter((r) => r.section === s.id)} />
        </Card>
      ))}

      <Card title={<span className="flex items-center gap-2"><History className="size-4" /> Time machine</span>} className="mt-4">
        {time_machine ? <TimeMachine r={time_machine} /> : (
          <Empty icon={<BrainIcon className="size-8" />} title="Not run yet">
            The time machine replays 2019–2025 news and prices day by day, lets the brain learn, then tests it on the last year it never saw.
          </Empty>
        )}
      </Card>
    </>
  );
}
