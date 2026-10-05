import clsx from "clsx";
import { Check, History, Lock, Pause, Play, Undo2, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  useAgents, useAnswer, useApplyChanges, useDropPending, useSuggest, useUndoChange,
  type AgentChange, type AgentInfo, type AgentQuestion, type AgentStatus, type AgentsView,
} from "../api";
import { Badge, Button, Card, Empty, ErrorNote, Loading, PageHeader, Stat } from "../components/ui";
import { ago } from "../format";

// --------------------------------------------------------------------------- helpers

const STATUS: Record<AgentStatus, { dot: string; word: string }> = {
  working: { dot: "bg-up shadow-[0_0_8px] shadow-up animate-pulse", word: "working" },
  active: { dot: "bg-up", word: "active" },
  idle: { dot: "bg-ink-3", word: "idle" },
  waiting: { dot: "bg-warn shadow-[0_0_8px] shadow-warn", word: "waiting for you" },
  paused: { dot: "bg-down", word: "paused" },
  sleeping: { dot: "bg-[#3a414c]", word: "sleeping" },
};

const hhmm = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function Dot({ status }: { status: AgentStatus }) {
  return <span className={clsx("size-2 shrink-0 rounded-full", STATUS[status].dot)} />;
}

const ANSWER_WORDS: Record<string, string> = {
  bearish: "Bad", neutral: "Neutral", bullish: "Good", accept: "Accept", reject: "Reject", approve: "Approve", refuse: "Refuse",
};

// ---------------------------------------------------------------------------- team chart

function Node({ a, selected, onPick, className }: { a: AgentInfo; selected: boolean; onPick: () => void; className?: string }) {
  return (
    <button
      onClick={onPick}
      className={clsx(
        "relative flex flex-col rounded-2xl border bg-panel-2 px-3 py-2.5 text-left transition hover:border-accent/50",
        selected ? "border-accent ring-3 ring-accent/20" : "border-line",
        className,
      )}
    >
      <span className="flex items-center gap-2 text-[13px] font-semibold"><Dot status={a.status} />{a.label}</span>
      <span className="mt-1 line-clamp-2 min-h-[2.4em] text-xs text-ink-2">{a.doing}</span>
      <span className="mt-1.5 flex flex-wrap gap-1.5 empty:hidden">
        {a.questions > 0 && <Badge tone="warn">{a.questions} question{a.questions > 1 ? "s" : ""}</Badge>}
        {a.paused && <Badge tone="down">paused</Badge>}
        {a.status === "sleeping" && <Badge>sleeping</Badge>}
        {a.custom && <Badge tone="info">your desk</Badge>}
        {a.watching.length > 0 && <Badge tone="warn">{a.watching.length} on watch</Badge>}
        {a.open_trades.length > 0 && <Badge tone="info">{a.open_trades.length} open</Badge>}
      </span>
    </button>
  );
}

function Connector() {
  return <div className="mx-auto h-5 w-px bg-[#2d333d]" />;
}

function TeamChart({ agents, selected, onPick }: { agents: AgentInfo[]; selected: string; onPick: (id: string) => void }) {
  const by = (pred: (a: AgentInfo) => boolean) => agents.filter(pred);
  const node = (a: AgentInfo, className?: string) => (
    <Node key={a.id} a={a} selected={a.id === selected} onPick={() => onPick(a.id)} className={className} />
  );
  const boss = by((a) => a.id === "orchestrator");
  const managers = by((a) => a.tier === "core" && a.id !== "orchestrator");
  const desksOf = (manager: string) => by((a) => a.tier === "desk" && a.parent === manager);
  const brain = by((a) => a.tier === "brain");
  const coins = by((a) => a.tier === "coin");
  const group = (title: string, items: AgentInfo[], cols: string) => (
    <div className="relative rounded-2xl border border-dashed border-[#2d333d] p-3 pt-4">
      <span className="absolute -top-2.5 left-3 bg-panel px-1.5 text-[11px] font-medium uppercase tracking-wider text-ink-3">{title}</span>
      <div className={clsx("grid gap-2.5", cols)}>{items.map((a) => node(a))}</div>
    </div>
  );
  const fast = by((a) => a.tier === "trading");
  return (
    <div>
      <div className="mx-auto max-w-xs">{boss.map((a) => node(a, "w-full"))}</div>
      <Connector />
      <div className="grid gap-2.5 sm:grid-cols-3">{managers.map((a) => node(a))}</div>
      <Connector />
      <div className="grid gap-5">
        {group("News desks · each hires short-lived workers", desksOf("news_manager"), "grid-cols-2 lg:grid-cols-4")}
        {group("Price desks", desksOf("price_manager"), "grid-cols-1 sm:grid-cols-3")}
        {group("Risk desks", desksOf("risk_manager"), "grid-cols-1 sm:grid-cols-3")}
      </div>
      <Connector />
      <div className="mx-auto max-w-md">{brain.map((a) => node(a, "w-full"))}</div>
      <Connector />
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">{coins.map((a) => node(a))}</div>
      <div className="mt-6 border-t border-line pt-4">
        <div className="mb-2 text-[11px] font-medium uppercase tracking-wider text-ink-3">Fast loop · every minute</div>
        <div className="grid gap-2.5 sm:grid-cols-2">{fast.map((a) => node(a))}</div>
      </div>
      <div className="mt-4 flex flex-wrap gap-4 text-xs text-ink-3">
        {(["working", "active", "idle", "waiting", "sleeping", "paused"] as AgentStatus[]).map((s) => (
          <span key={s} className="flex items-center gap-1.5"><Dot status={s} />{STATUS[s].word}</span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- detail

function Label({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 mt-5 text-[11px] font-medium uppercase tracking-wider text-ink-3">{children}</div>;
}

function Slider({ label, value, fallback, onChange }: { label: string; value: number | null; fallback: number; onChange: (v: number | null) => void }) {
  const v = value ?? fallback;
  return (
    <div className="mt-3">
      <div className="flex justify-between text-[13px]">
        <span>{label}</span>
        <span className="num text-ink-3">
          {value == null ? <>system default <b className="text-ink">{fallback.toFixed(2)}</b></> : <b className="text-ink">{value.toFixed(2)}</b>}
        </span>
      </div>
      <input type="range" min={0} max={1} step={0.05} value={v} onChange={(e) => onChange(+e.target.value)} className="mt-1.5 w-full accent-[#3987e5]" />
      {value != null && <button onClick={() => onChange(null)} className="text-xs text-ink-3 hover:text-ink-2">back to system default</button>}
    </div>
  );
}

function Detail({ a, view }: { a: AgentInfo; view: AgentsView }) {
  const suggest = useSuggest();
  const desk = a.thresholds != null;
  const [conf, setConf] = useState<number | null>(null);
  const [mag, setMag] = useState<number | null>(null);
  const [text, setText] = useState("");
  useEffect(() => {
    setConf(a.thresholds?.min_confidence ?? null);
    setMag(a.thresholds?.min_magnitude ?? null);
    setText(a.instruction ?? "");
  }, [a.id, a.thresholds?.min_confidence, a.thresholds?.min_magnitude, a.instruction]);
  const pendingHere = view.pending.filter((p) => p.agent === a.id);
  const dirty = desk && (conf !== (a.thresholds?.min_confidence ?? null) || mag !== (a.thresholds?.min_magnitude ?? null) || text !== (a.instruction ?? ""));

  const saveDesk = async () => {
    if (conf !== (a.thresholds?.min_confidence ?? null)) await suggest.mutateAsync({ kind: "min_confidence", agent: a.id, value: conf });
    if (mag !== (a.thresholds?.min_magnitude ?? null)) await suggest.mutateAsync({ kind: "min_magnitude", agent: a.id, value: mag });
    if (text !== (a.instruction ?? "")) await suggest.mutateAsync({ kind: "instruction", agent: a.id, value: text });
  };

  return (
    <Card title={<span className="flex items-center gap-2"><Dot status={a.status} />{a.label}</span>}
      action={<Badge tone={a.status === "waiting" ? "warn" : a.status === "paused" ? "down" : "muted"}>{STATUS[a.status].word}</Badge>}>
      <p className="text-xs text-ink-3">{a.role}</p>
      <Label>Doing now</Label>
      <div className="rounded-xl border border-line bg-panel-2 px-3 py-2.5 text-[13px]">
        {a.doing}
        {a.updated_at && <div className="mt-1 text-xs text-ink-3">updated {ago(a.updated_at)}</div>}
      </div>

      {a.watching.length > 0 && (
        <>
          <Label>Coins on watch (news says yes, waiting for the chart)</Label>
          <ul className="space-y-1.5">
            {a.watching.map((w) => (
              <li key={w.symbol} className="flex items-center justify-between gap-2 rounded-xl border border-line bg-panel-2 px-3 py-2 text-[13px]">
                <span><b>{w.symbol}</b> · {w.action === "sell" ? "short" : "buy"} after {w.event_type} news · until {hhmm(w.until)}</span>
                <Button variant="ghost" className="px-2.5 py-1 text-xs" onClick={() => suggest.mutate({ kind: "unwatch", agent: `coin:${w.symbol}`, value: true })}>
                  Stop watching
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}

      {a.open_trades.length > 0 && (
        <>
          <Label>Open trades</Label>
          <ul className="space-y-1 text-[13px] text-ink-2">
            {a.open_trades.map((t) => <li key={t.symbol}><b className="text-ink">{t.symbol}</b> {t.action === "sell" ? "short" : "long"} from {t.entry} · stop-loss {t.stop.toFixed(4)}</li>)}
          </ul>
        </>
      )}

      <Label>Recent work</Label>
      {a.log.length === 0 ? <div className="text-[13px] text-ink-3">Nothing yet.</div> : (
        <ul className="max-h-64 overflow-y-auto pr-1 text-[12.5px]">
          {a.log.map((l, i) => (
            <li key={i} className="border-b border-line/70 py-1.5 text-ink-2 last:border-0">
              <span className="num mr-1.5 text-ink-3">{hhmm(l.at)}</span>{l.text}
            </li>
          ))}
        </ul>
      )}

      {(a.pausable || desk) && <Label>Your controls <span className="normal-case tracking-normal">(saved as suggestions; live after Apply)</span></Label>}
      {a.pausable && (
        <div className="flex items-center justify-between rounded-xl border border-line bg-panel-2 px-3 py-2.5 text-[13px]">
          <span>{a.paused ? "Paused" : "Active"}{a.id === "trading" && <span className="block text-xs text-ink-3">Pausing stops new trades; stop-losses keep working.</span>}</span>
          <Button variant="ghost" className="px-3 py-1.5 text-xs" loading={suggest.isPending}
            onClick={() => suggest.mutate({ kind: "pause", agent: a.id, value: !a.paused })}>
            {a.paused ? <><Play className="size-3.5" /> Suggest resume</> : <><Pause className="size-3.5" /> Suggest pause</>}
          </Button>
        </div>
      )}
      {desk && (
        <>
          <Slider label="News must be at least this sure" value={conf} fallback={view.defaults.min_confidence} onChange={setConf} />
          <Slider label="News must be at least this strong" value={mag} fallback={view.defaults.min_magnitude} onChange={setMag} />
          <Label>Written instruction for this desk</Label>
          <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} rows={3}
            placeholder="e.g. Treat exchange hacks above $50M as strongly bad news for that exchange's coin."
            className="w-full resize-none rounded-xl border border-line bg-panel-2 px-3 py-2 text-[13px] outline-none focus:border-accent/60" />
          <div className="mt-1 text-xs text-ink-3">Used when Gemini (or Claude) reads the news. Keyword scoring can't follow instructions.</div>
          <div className="mt-3 flex justify-end">
            <Button disabled={!dirty} loading={suggest.isPending} onClick={saveDesk} className="px-3 py-1.5 text-xs">Save as suggestion</Button>
          </div>
        </>
      )}
      {suggest.error && <div className="mt-3"><ErrorNote error={suggest.error} /></div>}
      {pendingHere.length > 0 && <div className="mt-3 text-xs text-accent">{pendingHere.length} suggestion(s) for this agent waiting for Apply.</div>}
    </Card>
  );
}

// ---------------------------------------------------------------------------- inbox

function Question({ q, who }: { q: AgentQuestion; who: string }) {
  const answer = useAnswer();
  const [form, setForm] = useState(false);
  const [label, setLabel] = useState(q.payload.suggested_label ?? "");
  const [desc, setDesc] = useState(q.payload.suggested_description ?? "");
  const [guide, setGuide] = useState("");
  const tone = (o: string) => (["accept", "approve"].includes(o) ? "bg-up text-white" : ["reject", "refuse"].includes(o) ? "border border-down/50 text-down" : "border border-line text-ink-2 hover:bg-white/5");
  return (
    <div className="flex flex-col gap-3 border-b border-line/70 px-5 py-4 last:border-0 sm:flex-row">
      <div className="grid size-8 shrink-0 place-items-center rounded-xl bg-warn/12 font-semibold text-warn">{q.kind === "refinement" ? "!" : "?"}</div>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold">{q.title}</div>
        <div className="mt-0.5 text-[12.5px] text-ink-2">{q.detail}</div>
        {q.payload.examples && (
          <ul className="mt-1.5 list-disc pl-5 text-xs text-ink-3">{q.payload.examples.map((e) => <li key={e}>{e}</li>)}</ul>
        )}
        <div className="mt-1 text-[11.5px] text-ink-3">
          from {who} · {ago(q.asked_at)}
          {q.payload.url && <> · <a href={q.payload.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">read the article</a></>}
        </div>
        {form && (
          <div className="mt-3 grid gap-2">
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Desk name, e.g. Stablecoins" className="rounded-xl border border-line bg-panel-2 px-3 py-1.5 text-[13px] outline-none focus:border-accent/60" />
            <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What it covers, as keywords: stablecoin depeg usdt usdc reserve" className="rounded-xl border border-line bg-panel-2 px-3 py-1.5 text-[13px] outline-none focus:border-accent/60" />
            <input value={guide} onChange={(e) => setGuide(e.target.value)} placeholder="How it should judge the news (optional)" className="rounded-xl border border-line bg-panel-2 px-3 py-1.5 text-[13px] outline-none focus:border-accent/60" />
            <div className="flex gap-2">
              <Button className="px-3 py-1.5 text-xs" disabled={!label.trim() || !desc.trim()} loading={answer.isPending}
                onClick={() => answer.mutate({ id: q.id, value: "approve", label, description: desc, guidance: guide })}>Suggest this desk</Button>
              <Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => setForm(false)}>Cancel</Button>
            </div>
          </div>
        )}
        {answer.error && <div className="mt-2"><ErrorNote error={answer.error} /></div>}
      </div>
      <div className="flex shrink-0 flex-wrap items-start gap-1.5">
        {q.pending ? <Badge tone="info"><Check className="size-3" /> answered · waiting for Apply</Badge> : q.options.map((o) => (
          <button key={o} disabled={answer.isPending}
            onClick={() => (q.kind === "desk" && o === "approve" ? setForm(true) : answer.mutate({ id: q.id, value: o }))}
            className={clsx("rounded-[10px] px-2.5 py-1 text-xs font-semibold transition disabled:opacity-50", tone(o))}>
            {ANSWER_WORDS[o] ?? o}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- changes

function ChangeRow({ c, action }: { c: AgentChange; action?: ReactNode }) {
  return (
    <div className="flex items-start gap-3 border-b border-line/70 px-5 py-3 last:border-0">
      <div className="min-w-0 flex-1">
        <div className={clsx("text-[13px] font-semibold", c.undone_at && "text-ink-3 line-through")}>{c.title}</div>
        <div className="mt-1 inline-flex max-w-full flex-wrap items-center gap-1.5 rounded-lg bg-panel-2 px-2 py-0.5 font-mono text-xs">
          <span className="truncate text-down/90 line-through">{c.before}</span><span className="text-ink-3">→</span><span className="truncate text-up">{c.after}</span>
        </div>
        <div className="mt-1 text-[11.5px] text-ink-3">
          {c.applied_at ? `applied ${ago(c.applied_at)}` : `suggested ${ago(c.suggested_at)}`}{c.undone_at && ` · undone ${ago(c.undone_at)}`}
        </div>
      </div>
      {action}
    </div>
  );
}

function HistoryPanel({ items, onClose }: { items: AgentChange[]; onClose: () => void }) {
  const undo = useUndoChange();
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-md flex-col border-l border-line bg-panel">
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <span className="text-sm font-semibold">Applied changes</span>
          <button onClick={onClose} className="rounded-lg p-1.5 text-ink-3 hover:bg-white/5" aria-label="Close"><X className="size-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {items.length === 0 ? <Empty title="No changes applied yet" /> : items.map((c) => (
            <ChangeRow key={c.id} c={c} action={!c.undone_at && (
              <Button variant="ghost" className="px-2.5 py-1 text-xs" loading={undo.isPending && undo.variables === c.id} onClick={() => undo.mutate(c.id)}>
                <Undo2 className="size-3.5" /> Undo
              </Button>
            )} />
          ))}
        </div>
        {undo.error && <div className="p-4"><ErrorNote error={undo.error} /></div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- page

export default function Agents() {
  const q = useAgents();
  const apply = useApplyChanges();
  const drop = useDropPending();
  const [selected, setSelected] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const view = q.data;
  const byId = useMemo(() => new Map(view?.agents.map((a) => [a.id, a]) ?? []), [view]);
  useEffect(() => {
    if (view && !byId.has(selected)) {
      setSelected(view.agents.find((a) => a.questions > 0)?.id ?? "orchestrator");
    }
  }, [view, byId, selected]);

  if (q.isLoading) return <Loading />;
  if (q.error || !view) return <ErrorNote error={q.error ?? "no data"} />;

  const current = byId.get(selected);
  const busy = view.agents.filter((a) => a.status === "working" || a.status === "active").length;
  const sleeping = view.agents.filter((a) => a.status === "sleeping").length;
  const paused = view.agents.filter((a) => a.paused).length;
  const n = view.pending.length;
  const nextIn = view.cycle.next_at ? Math.round((new Date(view.cycle.next_at).getTime() - Date.now()) / 60000) : null;

  const applyButton = (
    <Button disabled={n === 0} loading={apply.isPending} onClick={() => apply.mutate()}>
      <Check className="size-4" /> Apply {n} change{n === 1 ? "" : "s"}
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Agents"
        subtitle={<>Your AI team, live. See who is doing what, answer their questions, and suggest changes. Suggestions wait for you to press <b>Apply</b>; every applied change is logged and can be undone.</>}
        actions={<>
          <Button variant="ghost" onClick={() => setShowHistory(true)}><History className="size-4" /> History ({view.history.length})</Button>
          {applyButton}
        </>}
      />
      {apply.error && <div className="mb-4"><ErrorNote error={apply.error} /></div>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Research cycle" value={view.cycle.last_at ? hhmm(view.cycle.last_at) : "—"}
          sub={view.cycle.running ? "running now" : nextIn == null ? "not started yet" : nextIn > 0 ? `next in ${nextIn} min` : "next one due now"} />
        <Stat label="Agents active" value={<>{busy} <span className="text-sm text-ink-3">of {view.agents.length}</span></>}
          sub={[sleeping && `${sleeping} sleeping`, paused && `${paused} paused`].filter(Boolean).join(" · ") || "in the last 20 minutes"} />
        <Stat label="Waiting for your answer" value={view.questions.filter((x) => !x.pending).length} tone={view.questions.some((x) => !x.pending) ? "text-warn" : ""} sub="see the inbox below" />
        <Stat label="Changes to apply" value={n} tone={n ? "text-accent" : ""} sub="not live until you press Apply" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_380px]">
        <Card title="Team chart" action={<span className="text-xs text-ink-3">click any box</span>}>
          <TeamChart agents={view.agents} selected={selected} onPick={setSelected} />
        </Card>
        {current && <div className="xl:sticky xl:top-6 xl:self-start"><Detail a={current} view={view} /></div>}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_380px]">
        <Card title={<span className="flex items-center gap-2">Needs your answer {view.questions.length > 0 && <Badge tone="warn">{view.questions.length}</Badge>}</span>} pad={false}>
          {view.questions.length === 0 ? <Empty title="No open questions">The agents ask here when they're unsure or want to change how they work.</Empty>
            : view.questions.map((x) => <Question key={x.id} q={x} who={byId.get(x.agent)?.label ?? x.agent} />)}
        </Card>
        <Card title={<span className="flex items-center gap-2">Changes waiting for Apply {n > 0 && <Badge tone="info">{n}</Badge>}</span>} pad={false}>
          {n === 0 ? <Empty title="Nothing waiting">Suggestions and answers collect here until you apply them.</Empty> : (
            <>
              {view.pending.map((c) => (
                <ChangeRow key={c.id} c={c} action={
                  <button onClick={() => drop.mutate(c.id)} className="rounded-lg border border-line p-1 text-ink-3 hover:text-down" aria-label="Remove"><X className="size-3.5" /></button>
                } />
              ))}
              <div className="flex items-center justify-between border-t border-line px-5 py-3">
                <Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => drop.mutate(null)}>Discard all</Button>
                {applyButton}
              </div>
            </>
          )}
        </Card>
      </div>

      <div className="mt-4 flex items-center gap-2 rounded-xl border border-line px-4 py-2.5 text-[12.5px] text-ink-2">
        <Lock className="size-4 shrink-0 text-ink-3" /> {view.locked} Those stay in Settings and the fixed rules.
      </div>

      {showHistory && <HistoryPanel items={view.history} onClose={() => setShowHistory(false)} />}
    </>
  );
}
