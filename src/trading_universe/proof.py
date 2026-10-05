"""Proving it makes money: the first three rollout gates of the BRD/TDD (version 2).

  1. Data check   sample ~100 price rows (and news/price pairs when news is given); more than 3% broken fails.
  2. Edge check   on the hidden last year: average profit per trade after ALL costs is positive, with enough
                  trades, the drawdown stays within 3% of the account, and it beats simple strategies
                  (just holding, a momentum rule, a moving-average rule).
  3. Robustness   still profitable with doubled costs, and no market type (rising / falling / flat,
                  wild / calm) or coin where it clearly loses.

Everything is point in time: a signal is decided on a finished daily candle and filled at the NEXT candle's
open (one candle late, on purpose). Every trade pays exchange fees, half the bid-ask spread on each side,
slippage that grows when the market is wild, and funding on shorts. Results are in R (1 R = the ₹ risk
budget lost at the stop-loss) and ₹.

What can be tested without old news (agreed option: news learns from today): our chart rules + risk rules
(market mood filter, short selling, stop-loss). The full system and a news-only strategy need news with
true publish times; the report says so. Gemini is never used here (it may know how old events ended).

Usage: python -m trading_universe.proof            (writes runs/proof/report.json and logs the experiment)
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest.engine import Setting
from .backtest.signals import long_signals, short_signals
from .experiments import Registry

log = logging.getLogger(__name__)

# Coins that were among the biggest on Binance at some point since 2019, including ones that later collapsed
# or were delisted, so the "coins as they were at each date" test isn't only made of survivors.
UNIVERSE_CANDIDATES = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT", "DOGEUSDT", "TRXUSDT", "DOTUSDT", "LTCUSDT",
    "LINKUSDT", "AVAXUSDT", "MATICUSDT", "BCHUSDT", "EOSUSDT", "XLMUSDT", "ETCUSDT", "LUNAUSDT", "FTTUSDT",
    "UNIUSDT", "ATOMUSDT", "FILUSDT", "SHIBUSDT", "ICPUSDT", "VETUSDT", "XTZUSDT", "NEOUSDT", "SUIUSDT", "TONUSDT",
)


# ------------------------------------------------------------------------------- costs


@dataclass(frozen=True)
class CostModel:
    fee: float = 0.001  # per side (Binance taker 0.1%)
    half_spread: float = 0.0002  # half the bid-ask gap, paid on each side
    slippage: float = 0.0005  # per side in a calm market; up to 3x when the coin is swinging hard
    funding_per_day: float = 0.0003  # shorts on perpetual futures (0.01% every 8 hours)

    def times(self, k: float) -> CostModel:
        return CostModel(self.fee * k, self.half_spread * k, self.slippage * k, self.funding_per_day * k)


# ------------------------------------------------------------------------------ trades


@dataclass(frozen=True)
class Trade:
    symbol: str
    side: int  # +1 long, -1 short
    signal_at: str  # day the signal was decided (finished candle)
    entry_at: str
    exit_at: str
    entry: float
    exit: float
    reason: str  # rule | stop_loss | end
    ret: float  # net return after all costs
    r: float  # ret / stop distance: what the trade made in R
    trend: str  # market type when the signal fired: rising / falling / flat
    swings: str  # wild / calm


def regimes(market: pd.DataFrame) -> pd.Series:
    """Rising / falling / flat market, from Bitcoin vs its 200-day average and that average's direction."""
    c = market["close"]
    sma = c.rolling(200).mean()
    slope = sma - sma.shift(20)
    out = pd.Series("flat", index=market.index)
    out[(c > sma) & (slope > 0)] = "rising"
    out[(c < sma) & (slope < 0)] = "falling"
    out[sma.isna()] = "unknown"
    return out


def swing_ratio(df: pd.DataFrame) -> pd.Series:
    """How hard a coin is swinging now vs its usual (30-day volatility / its median so far)."""
    v = np.log(df["close"]).diff().rolling(30).std()
    return (v / v.expanding(min_periods=180).median()).fillna(1.0)


class CoinBook:
    """One coin's trading, candle by candle. A signal on day i's finished candle is filled at day i+1's
    open. `entries`/`exits`: per side (+1 long, -1 short) boolean series; long wins if both fire."""

    def __init__(self, symbol: str, df: pd.DataFrame, entries: Mapping[int, pd.Series], exits: Mapping[int, pd.Series],
                 stop_pct: float | None, sizing_stop: float, costs: CostModel, trend: pd.Series,
                 allowed: pd.Series | None = None) -> None:
        self.symbol, self.df, self.stop_pct, self.sizing_stop, self.costs = symbol, df, stop_pct, sizing_stop, costs
        self.idx = df.index
        self.n = len(df)
        self.o, self.h, self.lo, self.c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
        self.ratio = swing_ratio(df).to_numpy()
        self.tr = trend.reindex(self.idx, method="ffill").fillna("unknown").to_numpy()
        self.en = {s: v.reindex(self.idx).fillna(False).to_numpy(dtype=bool) for s, v in entries.items()}
        self.ex = {s: v.reindex(self.idx).fillna(False).to_numpy(dtype=bool) for s, v in exits.items()}
        self.ok = np.ones(self.n, dtype=bool) if allowed is None else allowed.reindex(self.idx).fillna(False).to_numpy(dtype=bool)
        self.trades: list[Trade] = []
        self.side = 0
        self.entry_px = self.stop = 0.0
        self.entry_i = self.signal_i = 0
        self.pending: tuple[str, int, int] | None = None  # ("enter", side, signal day) or ("exit", 0, day)

    def _fill(self, px: float, i: int, buy: bool) -> float:
        cost = self.costs.half_spread + self.costs.slippage * min(max(self.ratio[i], 1.0), 3.0)
        return px * (1 + cost) if buy else px * (1 - cost)

    def _close(self, i: int, px_raw: float, reason: str) -> None:
        exit_px = self._fill(px_raw, i, buy=self.side < 0)
        if self.side > 0:
            ret = exit_px / self.entry_px - 1
        else:
            days = (self.idx[i] - self.idx[self.entry_i]) / pd.Timedelta(days=1)
            ret = (self.entry_px - exit_px) / self.entry_px - self.costs.funding_per_day * days
        ret -= 2 * self.costs.fee
        s = self.signal_i
        self.trades.append(Trade(self.symbol, self.side, self.idx[s].isoformat(), self.idx[self.entry_i].isoformat(),
                                 self.idx[i].isoformat(), round(float(self.entry_px), 8), round(float(exit_px), 8), reason,
                                 round(float(ret), 6), round(float(ret) / self.sizing_stop, 4), str(self.tr[s]),
                                 "wild" if self.ratio[s] > 1 else "calm"))
        self.side = 0

    def morning(self, i: int) -> None:
        """Fill yesterday's decision at today's open, then check the stop-loss during the day."""
        if self.pending is not None:
            kind, s, sig = self.pending
            self.pending = None
            if kind == "enter" and self.side == 0:
                self.side, self.signal_i, self.entry_i = s, sig, i
                self.entry_px = self._fill(self.o[i], i, buy=s > 0)
                self.stop = self.o[i] * (1 - s * self.stop_pct) if self.stop_pct else 0.0
            elif kind == "exit" and self.side != 0:
                self._close(i, self.o[i], "rule")
        if self.side != 0 and self.stop_pct:
            hit = self.lo[i] <= self.stop if self.side > 0 else self.h[i] >= self.stop
            if hit:  # a gap through the stop fills at the open, worse than the stop
                self._close(i, min(self.stop, self.o[i]) if self.side > 0 else max(self.stop, self.o[i]), "stop_loss")

    def wants(self, i: int) -> int:
        """At day i's close: the side a new trade would take (0 = none)."""
        if self.side != 0 or self.pending is not None or i >= self.n - 1 or not self.ok[i]:
            return 0
        return next((s for s in (1, -1) if s in self.en and self.en[s][i]), 0)

    def evening(self, i: int, enter: int = 0) -> None:
        """At day i's close: decide an exit, or (if allowed) an entry, to be filled tomorrow."""
        if i >= self.n - 1:
            return
        if self.side != 0:
            if self.side in self.ex and self.ex[self.side][i]:
                self.pending = ("exit", 0, i)
        elif enter:
            self.pending = ("enter", enter, i)

    def finish(self) -> list[Trade]:
        if self.side != 0:
            self._close(self.n - 1, self.c[-1], "end")
        return self.trades

    @property
    def busy(self) -> int:
        """+1/-1 if a trade is open or about to open on this side, else 0."""
        if self.side:
            return self.side
        return self.pending[1] if self.pending and self.pending[0] == "enter" else 0


def simulate(symbol: str, df: pd.DataFrame, entries: Mapping[int, pd.Series], exits: Mapping[int, pd.Series],
             stop_pct: float | None, sizing_stop: float, costs: CostModel, trend: pd.Series,
             allowed: pd.Series | None = None) -> list[Trade]:
    """One coin on its own, without any limit on other coins' trades."""
    if len(df) < 2:
        return []
    book = CoinBook(symbol, df, entries, exits, stop_pct, sizing_stop, costs, trend, allowed)
    for i in range(book.n):
        book.morning(i)
        book.evening(i, book.wants(i))
    return book.finish()


def simulate_portfolio(books: Sequence[CoinBook], max_open: int | None = None, max_shorts: int | None = None) -> list[Trade]:
    """All coins together, day by day, with the live agent's limits: at most `max_open` trades and at most
    `max_shorts` short trades open (or ordered) at the same time. When more coins signal on the same day than
    there are free places, coins earlier in the list go first."""
    books = [b for b in books if b.n >= 2]
    if not books:
        return []
    days = sorted(set().union(*(b.idx for b in books)))
    pos = [dict(zip(b.idx, range(b.n))) for b in books]
    for day in days:
        today = [(b, p[day]) for b, p in zip(books, pos) if day in p]
        for b, i in today:
            b.morning(i)
        for b, i in today:  # exits first, so their places free up only tomorrow (conservative)
            b.evening(i)
        for b, i in today:
            s = b.wants(i)
            if not s:
                continue
            busy = [x.busy for x in books]
            if max_open is not None and sum(1 for x in busy if x) >= max_open:
                continue
            if s < 0 and max_shorts is not None and sum(1 for x in busy if x < 0) >= max_shorts:
                continue
            b.evening(i, s)
    return [t for b in books for t in b.finish()]


# --------------------------------------------------------------------------- strategies


@dataclass(frozen=True)
class Plan:
    """What to test: our price rules with the risk rules, as set on the Settings page."""

    setting: Setting = Setting(20, 10, ("engulfing", "wick", "breakout"), 0.02)
    market_filter: bool = True
    shorts: bool = True
    max_open: int | None = 5  # live agent: at most 5 trades open at once
    max_shorts: int | None = 2  # live agent: at most 2 of them short

    def limits_label(self) -> str:
        return f"at most {self.max_open} trades open, {self.max_shorts if self.shorts else 0} short"


def market_ok(market: pd.DataFrame, days: int = 200) -> pd.Series:
    c = market["close"]
    return (c > c.rolling(days).mean()) & c.rolling(days).mean().notna()


def our_rules(plan: Plan, market: pd.DataFrame) -> Callable[[pd.DataFrame], tuple[dict, dict, float | None]]:
    mood = market_ok(market)

    def build(df: pd.DataFrame):
        s = plan.setting
        le, lx = long_signals(df, s.trend_window, s.breakout_window, s.triggers)
        entries, exits = {1: le}, {1: lx}
        if plan.market_filter:
            up = mood.reindex(df.index, method="ffill").fillna(False).astype(bool)
            entries[1] = le & up
            if plan.shorts:
                se, sx = short_signals(df, s.trend_window, s.breakout_window, s.triggers)
                entries[-1], exits[-1] = se & ~up, sx
        return entries, exits, s.stop_loss_pct

    return build


def momentum_rule(days: int = 20):
    def build(df: pd.DataFrame):
        m = df["close"] / df["close"].shift(days) - 1
        return {1: m > 0}, {1: m <= 0}, None

    return build


def moving_average_rule(days: int = 50):
    def build(df: pd.DataFrame):
        sma = df["close"].rolling(days).mean()
        return {1: df["close"] > sma}, {1: df["close"] < sma}, None

    return build


def hold_trades(frames: Mapping[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp, costs: CostModel,
                sizing_stop: float, trend: pd.Series) -> list[Trade]:
    """Just holding: buy each coin at the start of the period, sell at the end, sized like one trade."""
    out = []
    for sym, df in frames.items():
        sub = df[(df.index >= start) & (df.index <= end)]
        if len(sub) < 2:
            continue
        en = pd.Series(False, index=sub.index)
        en.iloc[0] = True  # decided on the first day, bought at the next open
        out += simulate(sym, sub, {1: en}, {1: pd.Series(False, index=sub.index)}, None, sizing_stop, costs, trend)
    return out


# ------------------------------------------------------------------------------ scoring


def score(trades: Sequence[Trade], risk_inr: float, account_inr: float) -> dict:
    if not trades:
        return {"trades": 0, "won": 0, "win_rate": 0.0, "avg_r": 0.0, "total_r": 0.0, "profit_inr": 0.0,
                "avg_return_pct": 0.0, "profit_factor": 0.0, "max_drawdown_r": 0.0, "max_drawdown_pct": 0.0, "worst_r": 0.0}
    r = pd.Series([t.r for t in sorted(trades, key=lambda t: t.exit_at)], dtype=float)
    eq = r.cumsum()
    dd = float((eq.cummax().clip(lower=0) - eq).max())
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {"trades": len(r), "won": int((r > 0).sum()), "win_rate": round(float((r > 0).mean()), 3),
            "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 2),
            "profit_inr": round(float(r.sum()) * risk_inr, 0), "avg_return_pct": round(float(np.mean([t.ret for t in trades])) * 100, 3),
            "profit_factor": round(float(gains / losses), 2) if losses > 0 else None, "max_drawdown_r": round(dd, 2),
            "max_drawdown_pct": round(dd * risk_inr / account_inr * 100, 2), "worst_r": round(float(r.min()), 2)}


def breakdown(trades: Sequence[Trade], key: Callable[[Trade], str], risk_inr: float, account_inr: float) -> dict[str, dict]:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        groups[key(t)].append(t)
    return {k: score(v, risk_inr, account_inr) for k, v in sorted(groups.items())}


# ---------------------------------------------------------------------------- data check


def data_check(frames: Mapping[str, pd.DataFrame], news: Sequence | None = None, sample: int = 100, seed: int = 7,
               max_defects: float = 0.03) -> dict:
    """Sample price rows (and news/price pairs) and look for broken data: missing days, duplicate or
    unsorted times, empty or impossible prices. Fails if more than `max_defects` of the samples are bad."""
    rng = np.random.default_rng(seed)
    rows = [(s, i) for s, df in frames.items() for i in range(1, len(df))]
    picks = [rows[k] for k in rng.choice(len(rows), size=min(sample, len(rows)), replace=False)] if rows else []
    problems: list[str] = []
    for sym, i in picks:
        df = frames[sym]
        t, prev = df.index[i], df.index[i - 1]
        r = df.iloc[i]
        bad = None
        if t <= prev:
            bad = "time not after the previous candle"
        elif t - prev != pd.Timedelta(days=1):
            bad = f"gap of {(t - prev).days} days"
        elif r[["open", "high", "low", "close"]].isna().any() or (r[["open", "high", "low", "close"]] <= 0).any():
            bad = "missing or non-positive price"
        elif r["high"] < max(r["open"], r["close"]) or r["low"] > min(r["open"], r["close"]) or r.get("volume", 0) < 0:
            bad = "impossible candle (high/low don't contain open/close)"
        if bad:
            problems.append(f"{sym} {t:%Y-%m-%d}: {bad}")
    checked = len(picks)
    news_checked = 0
    if news:
        items = list(news)
        for k in rng.choice(len(items), size=min(sample, len(items)), replace=False):
            item = items[k]
            news_checked += 1
            day = pd.Timestamp(item.published).tz_convert(None).normalize()
            if not item.title.strip():
                problems.append(f"news {item.item_id}: empty headline")
            for sym in item.symbols:
                df = frames.get(sym)
                if df is not None and df.index[0] <= day <= df.index[-1] and day not in df.index:
                    problems.append(f"news {item.item_id}: no {sym} candle on {day:%Y-%m-%d}")
                    break
    total = checked + news_checked
    rate = len(problems) / total if total else 1.0
    return {"price_rows_checked": checked, "news_pairs_checked": news_checked, "defects": len(problems),
            "defect_rate": round(rate, 4), "max_defect_rate": max_defects, "passed": total > 0 and rate <= max_defects,
            "examples": problems[:10]}


# --------------------------------------------------------------------------- the check


@dataclass
class Rules:
    """Pass/fail rules, fixed before the run and written into the experiment log."""

    min_exam_trades: int = 30
    min_avg_r: float = 0.0  # average profit per trade after costs must be above this
    max_drawdown_pct: float = 3.0  # of the account
    cost_stress: float = 2.0  # robustness: costs multiplied by this
    min_group_trades: int = 10  # market types / coins with fewer trades are not judged


@dataclass
class ProofConfig:
    coins: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    exam_days: int = 365
    risk_inr: float = 250.0
    account_inr: float = 88_000.0  # paper account: 1,000 USDT at ₹88
    costs: CostModel = field(default_factory=CostModel)
    plan: Plan = field(default_factory=Plan)
    rules: Rules = field(default_factory=Rules)
    market_symbol: str = "BTCUSDT"
    limit_choices: tuple[tuple[int, ...], tuple[int, ...]] = ((5, 4, 3, 2), (2, 1))  # (max open, max shorts) to try


def universe_mask(frames: Mapping[str, pd.DataFrame], size: int = 5, window: int = 30, min_history: int = 200) -> dict[str, pd.Series]:
    """For each coin, the days on which it was among the `size` most traded coins (by money traded in the
    last `window` days, re-picked at the start of each month, using only data up to then)."""
    turnover = pd.DataFrame({s: (df["close"] * df["volume"]).rolling(window).sum().where(np.arange(len(df)) >= min_history)
                             for s, df in frames.items()})
    first_day = turnover.groupby(turnover.index.to_period("M")).head(1)
    picks = first_day.rank(axis=1, ascending=False, method="first") <= size
    daily = picks.reindex(turnover.index, method="ffill").fillna(False)
    return {s: daily[s].astype(bool) for s in frames}


def run(frames: Mapping[str, pd.DataFrame], cfg: ProofConfig, universe: Mapping[str, pd.DataFrame] | None = None,
        news: Sequence | None = None) -> dict:
    market = frames.get(cfg.market_symbol)
    if market is None:
        raise ValueError(f"{cfg.market_symbol} prices are needed for the market mood")
    last = max(df.index.max() for df in frames.values())
    cutoff = last - pd.Timedelta(days=cfg.exam_days)
    first = min(df.index.min() for df in frames.values()) + pd.Timedelta(days=200)  # after the long averages warm up
    trend = regimes(market)
    sizing = cfg.plan.setting.stop_loss_pct
    rk, acct = cfg.risk_inr, cfg.account_inr

    def trades_of(build, costs: CostModel, fr: Mapping[str, pd.DataFrame] = frames, allowed=None,
                  plan: Plan | None = None) -> list[Trade]:
        books = []
        for sym, df in fr.items():
            if len(df) < 2:
                continue
            en, ex, stop = build(df)
            books.append(CoinBook(sym, df, en, ex, stop, sizing, costs, trend, None if allowed is None else allowed.get(sym)))
        out = (simulate_portfolio(books, plan.max_open, plan.max_shorts) if plan is not None
               else simulate_portfolio(books))
        return [t for t in out if pd.Timestamp(t.signal_at) >= first]

    def rules_trades(plan: Plan, costs: CostModel = cfg.costs, fr: Mapping[str, pd.DataFrame] = frames, allowed=None) -> list[Trade]:
        return trades_of(our_rules(plan, market), costs, fr, allowed, plan)

    def split(ts: list[Trade]) -> tuple[list[Trade], list[Trade]]:
        return [t for t in ts if pd.Timestamp(t.signal_at) <= cutoff], [t for t in ts if pd.Timestamp(t.signal_at) > cutoff]

    strategies: dict[str, dict] = {}

    def add(name: str, label: str, trades: list[Trade], kind: str) -> list[Trade]:
        p, e = split(trades)
        strategies[name] = {"label": label, "kind": kind, "practice": score(p, rk, acct), "exam": score(e, rk, acct)}
        return trades

    plan = cfg.plan
    ours = add("ours", f"Our chart + risk rules ({plan.limits_label()})", rules_trades(plan), "system")
    hold_p = hold_trades(frames, first, cutoff, cfg.costs, sizing, trend)
    hold_e = hold_trades(frames, cutoff, last, cfg.costs, sizing, trend)
    strategies["hold"] = {"label": "Just holding the coins", "kind": "baseline", "practice": score(hold_p, rk, acct),
                          "exam": score(hold_e, rk, acct)}
    add("momentum", "Momentum rule (hold while up over 20 days)", trades_of(momentum_rule(), cfg.costs), "baseline")
    add("moving_average", "Moving-average rule (hold while above the 50-day average)", trades_of(moving_average_rule(), cfg.costs), "baseline")
    # Switch-off tests: what each part adds.
    if cfg.plan.market_filter:
        add("no_mood_filter", "Without the market-mood filter (and so without shorts)",
            rules_trades(replace(plan, market_filter=False, shorts=False)), "switch_off")
    if cfg.plan.shorts and cfg.plan.market_filter:
        add("no_shorts", "Without short selling", rules_trades(replace(plan, shorts=False)), "switch_off")
    add("no_limits", "Without the open-trade limits (every coin on its own)",
        rules_trades(replace(plan, max_open=None, max_shorts=None)), "switch_off")
    add("ours_double_costs", f"Our rules with costs x{cfg.rules.cost_stress:g}", rules_trades(plan, cfg.costs.times(cfg.rules.cost_stress)), "stress")
    if universe:
        allowed = universe_mask(universe)
        add("ours_universe", "Our rules on the 5 most traded coins of each month (incl. later-collapsed coins)",
            rules_trades(plan, cfg.costs, universe, allowed), "survivorship")

    # Fewer trades / shorts open at once: chosen on the practice years ONLY (prices cut at the exam start),
    # by profit per unit of the worst dip; then the chosen one sits the exam once.
    practice_frames = {s: df[df.index <= cutoff] for s, df in frames.items()}
    choice_rows = []
    for mo in cfg.limit_choices[0]:
        for ms in (cfg.limit_choices[1] if plan.shorts else (0,)):
            if ms > mo:
                continue
            v = replace(plan, max_open=mo, max_shorts=ms)
            sc = score(rules_trades(v, fr=practice_frames), rk, acct)
            choice_rows.append({"max_open": mo, "max_shorts": ms, "practice": sc,
                                "profit_per_dip": round(sc["total_r"] / max(sc["max_drawdown_r"], 1.0), 2)})
    best = max(choice_rows, key=lambda x: x["profit_per_dip"])
    chosen = replace(plan, max_open=best["max_open"], max_shorts=best["max_shorts"])
    chosen_trades = ours
    if (chosen.max_open, chosen.max_shorts) != (plan.max_open, plan.max_shorts):
        chosen_trades = add("ours_chosen_limits", f"Our rules, {chosen.limits_label()} (chosen on practice years)",
                            rules_trades(chosen), "system")
        add("ours_chosen_double_costs", f"Chosen limits with costs x{cfg.rules.cost_stress:g}",
            rules_trades(chosen, cfg.costs.times(cfg.rules.cost_stress)), "stress")

    not_testable = {
        "full_system": "News + chart + risk together: needs old news with true publish times (news learns from today; "
                       "tested in shadow mode and paper trading).",
        "news_only": "News-only strategy: same reason.",
        "historical_weights": "The brain's learned weights act on news and research snapshots; measured once news exists.",
        "gemini": "Gemini is never used in replays (it may know how old events ended); measured in shadow mode.",
    }
    if news:
        not_testable["full_system"] = "Use the time machine with a news archive for the full system."

    # ---- gates
    r = cfg.rules
    baselines = {k: v["exam"]["total_r"] for k, v in strategies.items() if v["kind"] == "baseline"}

    def gates_for(key: str, trades: list[Trade], stressed_key: str) -> tuple[dict, dict, list[str], dict]:
        ex = strategies[key]["exam"]
        edge = {
            f"at least {r.min_exam_trades} trades in the exam": ex["trades"] >= r.min_exam_trades,
            "average profit per trade after costs is positive": ex["avg_r"] > r.min_avg_r,
            f"drawdown within {r.max_drawdown_pct:g}% of the account": ex["max_drawdown_pct"] <= r.max_drawdown_pct,
            **{f"beats {strategies[k]['label'].lower()}": ex["total_r"] > v for k, v in baselines.items()},
        }
        groups = {"market": breakdown(trades, lambda t: t.trend, rk, acct), "swings": breakdown(trades, lambda t: t.swings, rk, acct),
                  "coin": breakdown(trades, lambda t: t.symbol, rk, acct)}
        weak = [k for grp in groups.values() for k, v in grp.items()
                if k != "unknown" and v["trades"] >= r.min_group_trades and v["avg_r"] < 0]
        robust = {
            f"still profitable with costs x{r.cost_stress:g} (exam)": strategies[stressed_key]["exam"]["avg_r"] > 0,
            "no market type or coin where it clearly loses (whole period)": not weak,
        }
        return edge, robust, weak, groups

    edge_checks, robust_checks, weak, groups = gates_for("ours", ours, "ours_double_costs")
    e_ours = split(ours)[1]
    chosen_gates = None
    if chosen_trades is not ours:
        ce, cr, cw, cg = gates_for("ours_chosen_limits", chosen_trades, "ours_chosen_double_costs")
        chosen_gates = {"edge_check": {"passed": all(ce.values()), "checks": ce},
                        "robustness": {"passed": all(cr.values()), "checks": cr, "weak_spots": cw}, "breakdown": cg}
    dq = data_check(frames, news)
    report = {
        "period": {"start": first.isoformat(), "exam_start": cutoff.isoformat(), "end": last.isoformat()},
        "coins": list(frames),
        "plan": {"setting": asdict(plan.setting), "market_filter": plan.market_filter, "shorts": plan.shorts,
                 "max_open": plan.max_open, "max_shorts": plan.max_shorts},
        "costs": asdict(cfg.costs),
        "money": {"risk_per_trade_inr": rk, "account_inr": acct},
        "rules": asdict(r),
        "strategies": strategies,
        "breakdown": groups,
        "limit_choice": {"how": "chosen on the practice years only, by profit per unit of the worst dip",
                         "tried": choice_rows, "chosen": {"max_open": chosen.max_open, "max_shorts": chosen.max_shorts},
                         "same_as_live": chosen_trades is ours, "gates": chosen_gates},
        "not_testable": not_testable,
        "news_note": ("No old news was used: the news part learns from the system's own live collection from today on."
                      if not news else f"{len(news):,} archived news items were checked for true publish times."),
        "gates": {
            "data_check": {"passed": dq["passed"], "details": dq},
            "edge_check": {"passed": all(edge_checks.values()), "checks": edge_checks},
            "robustness": {"passed": all(robust_checks.values()), "checks": robust_checks, "weak_spots": weak},
        },
        "exam_trades": [asdict(t) for t in e_ours],
        "gemini": False,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    return report


# --------------------------------------------------------------------------------- CLI


def _plan_from_settings(runs: Path, shorts: bool | None) -> Plan:
    saved: dict = {}
    for name in ("settings.json", "best_setting.json"):
        p = runs / name
        if p.exists():
            saved = json.loads(p.read_text())
            break
    s = Plan().setting
    if all(k in saved for k in ("trend_window", "breakout_window", "triggers", "stop_loss_pct")):
        s = Setting(saved["trend_window"], saved["breakout_window"], tuple(saved["triggers"]), saved["stop_loss_pct"])
    return Plan(s, bool(saved.get("market_filter", True)), True if shorts is None else shorts)


def main(argv: list[str] | None = None) -> None:
    from .time_machine import load_prices

    p = argparse.ArgumentParser(prog="python -m trading_universe.proof", description=__doc__.split("\n\n")[0])
    p.add_argument("--start", default="2019-01-01", help="first day of prices to load (rules start ~200 days later)")
    p.add_argument("--exam-days", type=int, default=365)
    p.add_argument("--coins", default=",".join(ProofConfig().coins))
    p.add_argument("--no-shorts", action="store_true")
    p.add_argument("--no-universe", action="store_true", help="skip the coins-as-they-were-at-each-date test")
    p.add_argument("--runs", default="runs")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    runs = Path(a.runs)
    cfg = ProofConfig(coins=tuple(a.coins.split(",")), exam_days=a.exam_days,
                      plan=_plan_from_settings(runs, False if a.no_shorts else None))
    start = pd.Timestamp(a.start, tz="UTC").to_pydatetime() + pd.Timedelta(days=400)  # load_prices goes 400 days back
    print("Loading prices…")
    frames = load_prices(cfg.coins, start)
    universe = None
    if not a.no_universe:
        print("Loading the wider coin list for the survivorship test…")
        universe = load_prices(UNIVERSE_CANDIDATES, start)
    rep = run(frames, cfg, universe)
    out = runs / "proof"
    out.mkdir(parents=True, exist_ok=True)
    reg = Registry(runs / "experiments.jsonl")
    entry = reg.record("edge_check", rep["period"], rep["coins"], {"plan": rep["plan"], "costs": rep["costs"], "money": rep["money"]},
                       rep["rules"], {k: v["passed"] for k, v in rep["gates"].items()} | {"ours_exam": rep["strategies"]["ours"]["exam"]},
                       note=rep["news_note"])
    rep["experiment_id"], rep["exam_views_before"] = entry["id"], entry["exam_views_before"]
    (out / "report.json").write_text(json.dumps(rep, indent=1, default=str))

    print(f"\nPeriod {rep['period']['start'][:10]} → {rep['period']['end'][:10]}, exam from {rep['period']['exam_start'][:10]}"
          f" (looked at {entry['exam_views_before']} time(s) before)")
    for k, v in rep["strategies"].items():
        e, pr = v["exam"], v["practice"]
        print(f"  {v['label']:<75} exam {e['trades']:>4} trades {e['total_r']:+8.1f} R avg {e['avg_r']:+.2f} R dd {e['max_drawdown_pct']:.1f}%"
              f" | practice {pr['trades']:>4} trades {pr['total_r']:+8.1f} R")
    for g, v in rep["gates"].items():
        print(f"{g}: {'PASSED' if v['passed'] else 'FAILED'}")
        for check, ok in v.get("checks", {}).items():
            print(f"   {'✓' if ok else '✗'} {check}")
    lc = rep["limit_choice"]
    print("\nOpen-trade limits tried on the practice years (profit per unit of the worst dip):")
    for row in lc["tried"]:
        pr = row["practice"]
        print(f"   max {row['max_open']} open, {row['max_shorts']} short: {pr['total_r']:+8.1f} R, worst dip {pr['max_drawdown_r']:.1f} R"
              f" -> {row['profit_per_dip']:.2f}")
    print(f"   chosen: max {lc['chosen']['max_open']} open, {lc['chosen']['max_shorts']} short"
          + (" (same as the live rules)" if lc["same_as_live"] else ""))
    if lc["gates"]:
        for g in ("edge_check", "robustness"):
            v = lc["gates"][g]
            print(f"   chosen limits, {g}: {'PASSED' if v['passed'] else 'FAILED'}")
            for check, ok in v["checks"].items():
                print(f"      {'✓' if ok else '✗'} {check}")
    print(f"Experiment {entry['id']}; report: {out / 'report.json'}")


if __name__ == "__main__":
    main()
