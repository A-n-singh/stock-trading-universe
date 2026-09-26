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
}

// ---------------------------------------------------------------------------- fetch

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
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

export const useMarkets = (market: string, symbols: string[]) =>
  useQuery({
    queryKey: ["markets", market, symbols.join(",")],
    queryFn: () => call<{ items: MarketItem[]; errors: Record<string, string> }>(
      `/api/markets?market=${market}&symbols=${encodeURIComponent(symbols.join(","))}`),
    enabled: symbols.length > 0,
    refetchInterval: 60_000,
  });

export const useCandles = (symbol: string, market: string, days: number) =>
  useQuery({
    queryKey: ["candles", symbol, market, days],
    queryFn: () => call<CandleData>(`/api/candles/${symbol}?market=${market}&days=${days}`),
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
    mutationFn: (req: { market: string; symbols: string[]; holdout_days: number; min_trades: number; market_filter: boolean }) =>
      call<BacktestResult>("/api/backtest", { method: "POST", body: JSON.stringify(req) }),
  });
