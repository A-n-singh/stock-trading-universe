import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

// ----------------------------------------------------------------------------- types

export type Mood = "rising" | "falling" | null;

export interface MarketItem {
  symbol: string;
  last: number;
  change_1d: number | null;
  change_30d: number | null;
  change_1y: number | null;
  ma200: number | null;
  mood: Mood;
  spark: number[];
  from: string;
  to: string;
}

export interface CandleData {
  symbol: string;
  candles: { time: number; open: number; high: number; low: number; close: number; volume: number }[];
  trend: { time: number; value: number }[];
  buys: number[];
  trend_window: number;
}

export interface NewsSignal {
  direction: "bullish" | "bearish" | "neutral";
  magnitude: number;
  confidence: number;
  event_type: string;
  actionable: boolean;
  headline: string;
}

export interface Snapshot {
  symbol: string;
  direction_bias: "bullish" | "bearish" | "neutral";
  confidence: number;
  as_of: string;
  sector: string;
  risk_flags: string[];
  news: NewsSignal | null;
  rationale: string;
}

export interface Score {
  direction: string;
  magnitude: number;
  confidence: number;
  actionable: boolean;
  reason: string;
  lead: string;
  scorer: string;
}

export interface NewsItem {
  item_id: string;
  source: string;
  title: string;
  url: string;
  published: string;
  summary: string;
  kind: string;
  symbols: string[];
  event_type: string;
  scores: Score[];
}

export interface Status {
  started_at?: string;
  last_research_at?: string;
  last_trade_tick_at?: string;
  research_cycles?: number;
  trade_ticks?: number;
  scorer?: string;
  broker?: string;
  equity_usdt?: number;
  cash_usdt?: number;
  open_positions?: Record<string, number>;
  market_downtrend?: boolean;
  shorts?: boolean;
  last_events?: string[];
  errors?: string[];
}

export interface Trade {
  trade_id: string;
  symbol: string;
  action: string;
  quantity: number;
  entry_price: number;
  stop_price: number;
  risk_amount: number;
  opened_at: string;
  snapshot: Partial<Snapshot>;
  votes: { name: string; approve: boolean; reason: string }[];
  exit_price: number | null;
  closed_at: string | null;
  exit_reason: string | null;
  pnl: number | null;
  fees: number;
  invested: number;
  live_price: number | null;
  live_pnl: number | null;
  pct: number | null;
  r_multiple: number | null;
  held_s: number;
  event_type: string;
  desk: string;
}

export interface MemoryRecord {
  id: string;
  kind: "pattern" | "asset_note";
  owner_id: string;
  text: string;
  valid_from: string;
  evidence: [string, string][];
  refs: string[];
  outcomes: [string, boolean, string][];
  retired_at: string | null;
}

export interface MemoryResponse {
  memory: { records: MemoryRecord[]; dormant: string[] };
  refinements: { multipliers: Record<string, number>; tasks: Record<string, string | number>[] };
}

export interface Settings {
  risk_per_trade_inr: number;
  stop_loss_pct: number;
  trend_window: number;
  breakout_window: number;
  triggers: string[];
  coins: string[];
  market_filter: boolean;
  usdt_inr: number;
  allow_short: boolean;
}

export interface Score2 {
  trades: number;
  total_r: number;
  avg_r: number;
  win_rate: number;
  max_drawdown_r: number;
}

export interface BacktestRow {
  rank: string;
  setting: { trend_window: number; breakout_window: number; triggers: string[]; stop_loss_pct: number };
  passed: boolean;
  reason: string;
  practice: Score2;
  exam: Score2;
  hold_r: number | null;
  pass_kind: "" | "profit" | "beat_hold";
}

export interface BacktestResult {
  cutoff: string;
  practice_period: [string, string];
  exam_period: [string, string];
  settings_tested: number;
  settings_eligible: number;
  rows: BacktestRow[];
  chosen: BacktestRow["setting"] | null;
  curves: { name: string; color: string; points: { time: number; value: number }[] }[];
  risk_inr: number;
  hold_returns: Record<string, number>;
}

// ---------------------------------------------------------------------------- fetch

/** Thrown when the server wants a login; the app then shows the login screen. */
export class AuthRequired extends Error {}

let onAuthRequired: () => void = () => {};
export const setAuthHandler = (fn: () => void) => { onAuthRequired = fn; };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, credentials: "same-origin", ...init });
  if (res.status === 401 && path !== "/api/login") {
    onAuthRequired();
    throw new AuthRequired("login required");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------- hooks

export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: () => call<Settings>("/api/settings") });

export const useMarkets = (symbols: string[]) =>
  useQuery({
    queryKey: ["markets", symbols.join(",")],
    queryFn: () => call<{ items: MarketItem[]; errors: Record<string, string> }>(
      `/api/markets?symbols=${encodeURIComponent(symbols.join(","))}`),
    enabled: symbols.length > 0,
    refetchInterval: 60_000,
  });

export const useCandles = (symbol: string, days: number) =>
  useQuery({
    queryKey: ["candles", symbol, days],
    queryFn: () => call<CandleData>(`/api/candles/${symbol}?days=${days}`),
    enabled: !!symbol,
    refetchInterval: 60_000,
  });

export const useSnapshots = () =>
  useQuery({ queryKey: ["snapshots"], queryFn: () => call<Record<string, Snapshot>>("/api/snapshots"), refetchInterval: 30_000 });

export const useNews = (coins: string[]) =>
  useQuery({
    queryKey: ["news", coins.join(",")],
    queryFn: () => call<NewsItem[]>(`/api/news?coins=${encodeURIComponent(coins.join(","))}`),
    refetchInterval: 60_000,
  });

export const useStatus = () => useQuery({ queryKey: ["status"], queryFn: () => call<Status>("/api/status"), refetchInterval: 15_000 });
export const useTrades = () => useQuery({ queryKey: ["trades"], queryFn: () => call<Trade[]>("/api/trades"), refetchInterval: 30_000 });
export const useMemory = () => useQuery({ queryKey: ["memory"], queryFn: () => call<MemoryResponse>("/api/memory") });
export const useRoadmap = () => useQuery({ queryKey: ["roadmap"], queryFn: () => call<{ markdown: string }>("/api/roadmap") });

function useAction<TIn, TOut>(fn: (x: TIn) => Promise<TOut>, invalidate: string[]) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] })) });
}

export const useRunResearch = () =>
  useAction(() => call<{ snapshots: Record<string, Snapshot> }>("/api/research/run", { method: "POST" }), ["snapshots", "news", "status", "memory"]);

export const useTradeStep = () =>
  useAction(
    () => call<{ events: { symbol: string; kind: string; detail: string }[] }>("/api/trade/step", { method: "POST" }),
    ["status", "trades", "memory"],
  );

export const useSaveSettings = () =>
  useAction((s: Settings) => call<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(s) }), ["settings", "candles"]);

export const useApplyBest = () =>
  useAction((s: BacktestRow["setting"]) => call<Settings>("/api/settings/apply-best", { method: "POST", body: JSON.stringify(s) }), [
    "settings",
    "candles",
  ]);

export const useBacktest = () =>
  useMutation({
    mutationFn: (req: { symbols: string[]; holdout_days: number; min_trades: number; market_filter: boolean; fair_exam: boolean; shorts: boolean }) =>
      call<BacktestResult>("/api/backtest", { method: "POST", body: JSON.stringify(req) }),
  });

// ---------------------------------------------------------------------------- login

export const useAuth = () =>
  useQuery({ queryKey: ["auth"], queryFn: () => call<{ required: boolean; logged_in: boolean }>("/api/auth"), staleTime: 60_000 });

export const useLogin = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (password: string) => call<{ ok: boolean }>("/api/login", { method: "POST", body: JSON.stringify({ password }) }),
    onSuccess: () => qc.invalidateQueries(),
  });
};

export const useLogout = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => call<{ ok: boolean }>("/api/logout", { method: "POST" }),
    onSuccess: () => {
      qc.setQueryData(["auth"], { required: true, logged_in: false });
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" }); // forget the data that was shown
    },
  });
};

// ---------------------------------------------------------------------------- agents page

export type AgentStatus = "working" | "active" | "idle" | "waiting" | "paused" | "sleeping";

export interface AgentInfo {
  id: string;
  label: string;
  role: string;
  parent: string | null;
  tier: "core" | "desk" | "coin" | "trading";
  custom?: boolean;
  status: AgentStatus;
  doing: string;
  updated_at: string | null;
  log: { at: string; text: string }[];
  questions: number;
  pausable: boolean;
  paused: boolean;
  watching: { symbol: string; action: string; event_type: string; since: string; until: string }[];
  open_trades: { symbol: string; action: string; entry: number; stop: number }[];
  thresholds: { min_confidence: number | null; min_magnitude: number | null } | null;
  instruction: string | null;
}

export interface AgentQuestion {
  id: string;
  agent: string;
  kind: "ruling" | "refinement" | "desk";
  title: string;
  detail: string;
  options: string[];
  payload: Record<string, unknown> & { examples?: string[]; url?: string };
  asked_at: string;
  pending: boolean;
}

export interface AgentChange {
  id: string;
  kind: string;
  agent: string;
  title: string;
  before: string;
  after: string;
  suggested_at: string;
  applied_at?: string;
  undone_at?: string | null;
}

export interface AgentsView {
  cycle: { last_at?: string; next_at?: string; every_s?: number; running?: boolean };
  agents: AgentInfo[];
  questions: AgentQuestion[];
  pending: AgentChange[];
  history: AgentChange[];
  defaults: { min_confidence: number; min_magnitude: number };
  locked: string;
}

export const useAgents = () =>
  useQuery({ queryKey: ["agents"], queryFn: () => call<AgentsView>("/api/agents"), refetchInterval: 5_000 });

export const useSuggest = () =>
  useAction((s: { kind: string; agent: string; value: unknown }) =>
    call<AgentChange>("/api/agents/suggest", { method: "POST", body: JSON.stringify(s) }), ["agents"]);

export const useAnswer = () =>
  useAction((a: { id: string; value: string; label?: string; description?: string; guidance?: string }) =>
    call<AgentChange>(`/api/agents/questions/${encodeURIComponent(a.id)}/answer`, { method: "POST", body: JSON.stringify(a) }), ["agents"]);

export const useDropPending = () =>
  useAction((id: string | null) => call<{ ok: boolean }>(id ? `/api/agents/pending/${id}` : "/api/agents/pending", { method: "DELETE" }), ["agents"]);

export const useApplyChanges = () =>
  useAction(() => call<{ applied: number }>("/api/agents/apply", { method: "POST" }), ["agents"]);

export const useUndoChange = () =>
  useAction((id: string) => call<{ ok: boolean }>(`/api/agents/history/${id}/undo`, { method: "POST" }), ["agents"]);
