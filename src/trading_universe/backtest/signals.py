"""Vectorised version of the Technical gate (`trading_agent/technical.py`).

Same rules, computed for every bar at once with pandas instead of one bar at a time, so
VectorBT can test thousands of settings in one pass. `tests/test_backtest.py` checks that
both versions agree bar by bar.
"""

from __future__ import annotations

from collections.abc import Collection

import numpy as np
import pandas as pd


def _patterns(df: pd.DataFrame, breakout_window: int, short: bool = False) -> dict[str, pd.Series]:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    po, pc = o.shift(1), c.shift(1)
    body = (c - o).abs()
    rng = h - l
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)
    if short:  # the bearish mirror images: bearish engulfing, shooting star, breakdown
        engulfing = (pc > po) & (c < o) & (o >= pc) & (c <= po)
        star = (rng > 0) & (upper_wick >= 2 * body) & (lower_wick <= np.maximum(body, 0.1 * rng))
        breakdown = c < l.shift(1).rolling(breakout_window).min()
        return {"engulfing": engulfing, "wick": star, "breakout": breakdown}
    engulfing = (pc < po) & (c > o) & (o <= pc) & (c >= po)
    hammer = (rng > 0) & (lower_wick >= 2 * body) & (upper_wick <= np.maximum(body, 0.1 * rng))
    breakout = c > h.shift(1).rolling(breakout_window).max()
    return {"engulfing": engulfing, "wick": hammer, "breakout": breakout}


def long_signals(
    df: pd.DataFrame, trend_window: int, breakout_window: int, triggers: Collection[str]
) -> tuple[pd.Series, pd.Series]:
    """Entries: close above its moving average AND an enabled pattern fires. Exits: close drops below it."""
    close = df["close"]
    trend = close.rolling(trend_window).mean()
    patterns = _patterns(df, breakout_window)
    fired = pd.Series(False, index=df.index)
    for name in triggers:
        fired |= patterns[name].fillna(False).astype(bool)
    warm = np.arange(len(df)) >= max(trend_window, breakout_window + 1) - 1
    entries = (close > trend) & fired & warm
    exits = (close < trend) & warm
    return entries.fillna(False).astype(bool), exits.fillna(False).astype(bool)


def short_signals(
    df: pd.DataFrame, trend_window: int, breakout_window: int, triggers: Collection[str]
) -> tuple[pd.Series, pd.Series]:
    """Mirror image for short selling: close below its average AND a bearish pattern. Exit: close back above it."""
    close = df["close"]
    trend = close.rolling(trend_window).mean()
    patterns = _patterns(df, breakout_window, short=True)
    fired = pd.Series(False, index=df.index)
    for name in triggers:
        fired |= patterns[name].fillna(False).astype(bool)
    warm = np.arange(len(df)) >= max(trend_window, breakout_window + 1) - 1
    entries = (close < trend) & fired & warm
    exits = (close > trend) & warm
    return entries.fillna(False).astype(bool), exits.fillna(False).astype(bool)
