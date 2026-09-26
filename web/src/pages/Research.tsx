import clsx from "clsx";
import { ExternalLink, RefreshCw, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { useNews, useRunResearch, useSettings, useSnapshots, type NewsItem } from "../api";
import { Badge, Button, Card, Empty, ErrorNote, Loading, Meter, PageHeader, Segmented } from "../components/ui";
import { ago, coin } from "../format";

const dirTone = (d?: string) => (d === "bullish" ? "up" : d === "bearish" ? "down" : "muted") as "up" | "down" | "muted";

export default function Research() {
  const settings = useSettings();
  const coins = settings.data?.coins ?? [];
  const snaps = useSnapshots();
  const research = useRunResearch();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [type, setType] = useState("all");
  const news = useNews(scope === "mine" ? coins : []);
  const types = useMemo(() => ["all", ...new Set((news.data ?? []).map((n) => n.event_type))], [news.data]);
  const items = (news.data ?? []).filter((n) => type === "all" || n.event_type === type);

  return (
    <>
      <PageHeader
        title="News & research"
        subtitle="The research team reads crypto news, scores each item (direction, size, trust), checks prices and risks, and writes one snapshot per coin. The trading agent only ever reads these snapshots."
        actions={<Button loading={research.isPending} onClick={() => research.mutate()}><RefreshCw className="size-4" /> Run research now</Button>}
      />
      {research.error && <div className="mb-4"><ErrorNote error={research.error} /></div>}

      {snaps.isLoading ? <Loading /> : snaps.data && Object.keys(snaps.data).length ? (
        <div className="grid gap-3 md:grid-cols-2">
          {Object.values(snaps.data).map((s) => (
            <Card key={s.symbol} title={
              <span className="flex items-center gap-2">
                <span className="text-base font-semibold text-ink">{coin(s.symbol)}</span>
                <Badge tone={dirTone(s.direction_bias)}>{s.direction_bias}</Badge>
                {s.news?.actionable && <Badge tone="info">act on news</Badge>}
              </span>
            } action={<span className="text-xs text-ink-3">{ago(s.as_of)}</span>}>
              <div className="flex flex-wrap items-center gap-3 text-xs text-ink-3">
                confidence <Meter value={s.confidence} />
                {s.risk_flags.map((f) => <Badge key={f} tone="warn"><ShieldAlert className="size-3" /> {f.replace("_", " ")}</Badge>)}
              </div>
              {s.news && (
                <div className="mt-3 rounded-xl border border-line bg-panel-2 p-3">
                  <div className="text-sm font-medium">{s.news.headline}</div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    <Badge tone={dirTone(s.news.direction)}>{s.news.direction}</Badge>
                    <Badge>{s.news.event_type}</Badge>
                    <Badge>size {s.news.magnitude.toFixed(1)}</Badge>
                    <Badge>trust {s.news.confidence.toFixed(1)}</Badge>
                  </div>
                </div>
              )}
              <p className="mt-3 text-sm leading-relaxed text-ink-2">{s.rationale}</p>
            </Card>
          ))}
        </div>
      ) : (
        <Card><Empty title="No snapshots yet">Press <b>Run research now</b>. It collects news, scores it and writes a snapshot per coin (10–60 seconds).</Empty></Card>
      )}

      <Card className="mt-6" pad={false} title="News feed" action={
        <div className="flex flex-wrap gap-2">
          <Segmented value={scope} onChange={setScope} options={[{ value: "mine", label: "My coins" }, { value: "all", label: "All" }]} />
          <select value={type} onChange={(e) => setType(e.target.value)}
            className="rounded-xl border border-line bg-panel-2 px-2 py-1 text-xs font-semibold text-ink-2 outline-none">
            {types.map((t) => <option key={t} value={t}>{t === "all" ? "All types" : t}</option>)}
          </select>
        </div>
      }>
        {news.isLoading ? <Loading /> : items.length ? (
          <ul className="divide-y divide-line">{items.map((n) => <NewsRow key={n.item_id} n={n} />)}</ul>
        ) : <Empty title="No news yet">News appears after the first research run.</Empty>}
      </Card>
    </>
  );
}

function NewsRow({ n }: { n: NewsItem }) {
  const sc = n.scores[0];
  return (
    <li className="flex gap-4 px-5 py-3">
      <div className="num w-20 shrink-0 pt-0.5 text-xs text-ink-3">{ago(n.published)}</div>
      <div className="min-w-0 flex-1">
        <a href={n.url} target="_blank" rel="noreferrer" className="group inline-flex items-start gap-1 text-sm font-medium hover:text-accent">
          {n.title} <ExternalLink className="mt-0.5 size-3 shrink-0 opacity-0 group-hover:opacity-100" />
        </a>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-ink-3">{n.source}</span>
          {n.symbols.map((s) => <Badge key={s} tone="info">{coin(s)}</Badge>)}
          <Badge>{n.event_type}</Badge>
          {sc && <Badge tone={dirTone(sc.direction)}>{sc.direction} · size {sc.magnitude.toFixed(1)} · trust {sc.confidence.toFixed(1)}</Badge>}
          {sc && <span className={clsx("text-xs", "text-ink-3")}>{sc.lead} desk · {sc.reason}</span>}
        </div>
      </div>
    </li>
  );
}
