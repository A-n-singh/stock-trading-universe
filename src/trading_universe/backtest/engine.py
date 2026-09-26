"""Run many settings at once with VectorBT and score them in R (multiples of the risk taken).

1 R = the amount lost when the stop-loss is hit = the ₹200–300 risk budget. Scoring in R
makes settings with different stop-loss sizes comparable, and ₹ results = R × budget.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .signals import long_signals

ALL_TRIGGERS = ("engulfing", "wick", "breakout")


@dataclass(frozen=True)
class Setting:
    trend_window: int
    breakout_window: int
    triggers: tuple[str, ...]
    stop_loss_pct: float

    def label(self) -> str:
        return f"trend={self.trend_window} breakout={self.breakout_window} triggers={'+'.join(self.triggers)} stop={self.stop_loss_pct:.1%}"


@dataclass(frozen=True)
class Costs:
    fees: float = 0.001  # per side; 0.1% is a typical crypto spot taker fee (Indian exchanges often charge more)
    slippage: float = 0.0005  # 5 bps


@dataclass(frozen=True)
class MarketProfile:
    """Defaults that differ between crypto and stocks."""

    name: str
    costs: Costs
    stop_losses: tuple[float, ...]


# Crypto moves several % a day, so stop-losses tighter than ~2% get hit by normal noise.
CRYPTO = MarketProfile("crypto", Costs(fees=0.001, slippage=0.0005), (0.02, 0.03, 0.05, 0.07, 0.10))
STOCK = MarketProfile("stock", Costs(fees=0.0003, slippage=0.0005), (0.01, 0.015, 0.02, 0.025, 0.03))
PROFILES = {p.name: p for p in (CRYPTO, STOCK)}


def build_grid(
    trend_windows: Iterable[int] = (10, 20, 30, 50, 100),
    breakout_windows: Iterable[int] = (5, 10, 20),
    stop_losses: Iterable[float] = CRYPTO.stop_losses,
    trigger_sets: Iterable[Sequence[str]] | None = None,
) -> list[Setting]:
    if trigger_sets is None:
        trigger_sets = [c for n in (1, 2, 3) for c in itertools.combinations(ALL_TRIGGERS, n)]
    return [
        Setting(t, b, tuple(trig), s)
        for t, b, trig, s in itertools.product(trend_windows, breakout_windows, trigger_sets, stop_losses)
    ]



def trade_r_multiples(
    data: Mapping[str, pd.DataFrame],
    settings: Sequence[Setting],
    costs: Costs = Costs(),
    count_entries_after: pd.Timestamp | None = None,
) -> list[pd.Series]:
    """For each setting, the R-multiple of every closed trade across all symbols, in exit-date order.

    `count_entries_after`: price history before this date is still used to warm up the moving
    averages, but only trades *entered* after it are counted (used for the hidden-year exam).
    """
    import vectorbt as vbt  # heavy import; only needed when actually backtesting

    per_setting: list[list[tuple[pd.Timestamp, float]]] = [[] for _ in settings]
    for df in data.values():
        # One column per setting: VectorBT then simulates every column in a single pass.
        cols = pd.RangeIndex(len(settings))
        entries = np.zeros((len(df), len(settings)), dtype=bool)
        exits = np.zeros_like(entries)
        cache: dict[tuple[int, int, tuple[str, ...]], tuple[np.ndarray, np.ndarray]] = {}
        for i, s in enumerate(settings):
            key = (s.trend_window, s.breakout_window, s.triggers)
            if key not in cache:
                en, ex = long_signals(df, *key)
                cache[key] = (en.to_numpy(), ex.to_numpy())
            entries[:, i], exits[:, i] = cache[key]
        if count_entries_after is not None:
            entries[df.index <= count_entries_after] = False
        entries = pd.DataFrame(entries, index=df.index, columns=cols)
        exits = pd.DataFrame(exits, index=df.index, columns=cols)
        stops = np.array([s.stop_loss_pct for s in settings])
        pf = vbt.Portfolio.from_signals(
            df["close"],
            entries,
            exits,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            sl_stop=pd.DataFrame(np.broadcast_to(stops, entries.shape), index=df.index, columns=cols),
            fees=costs.fees,
            slippage=costs.slippage,
            freq=pd.Series(df.index).diff().median() if len(df) > 1 else "1D",  # 1d, 4h, 1h ... candles
        )
        rec = pf.trades.values
        closed = rec[rec["status"] == 1]
        for col, exit_idx, ret in zip(closed["col"], closed["exit_idx"], closed["return"]):
            per_setting[col].append((df.index[exit_idx], ret / stops[col]))
    out = []
    for trades in per_setting:
        trades.sort(key=lambda t: t[0])
        out.append(pd.Series([r for _, r in trades], index=[d for d, _ in trades], dtype=float))
    return out


@dataclass(frozen=True)
class Score:
    trades: int
    total_r: float
    avg_r: float
    win_rate: float
    max_drawdown_r: float

    @classmethod
    def of(cls, r: pd.Series) -> Score:
        if r.empty:
            return cls(0, 0.0, 0.0, 0.0, 0.0)
        equity = r.cumsum()
        drawdown = float((equity.cummax().clip(lower=0) - equity).max())
        return cls(len(r), float(r.sum()), float(r.mean()), float((r > 0).mean()), drawdown)

    def rupees(self, risk_per_trade: float = 250.0) -> float:
        return self.total_r * risk_per_trade


def run_grid(data: Mapping[str, pd.DataFrame], settings: Sequence[Setting], costs: Costs = Costs(), count_entries_after: pd.Timestamp | None = None) -> list[Score]:
    return [Score.of(r) for r in trade_r_multiples(data, settings, costs, count_entries_after)]
