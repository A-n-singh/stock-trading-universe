"""Technical leg of the AND-gate: candlestick / price-pattern confirmation for entry timing."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from ..models import Action, Candle, GateVote


def sma(values: Sequence[float], n: int) -> float:
    return sum(values[-n:]) / n


def bullish_engulfing(prev: Candle, cur: Candle) -> bool:
    return prev.close < prev.open and cur.close > cur.open and cur.open <= prev.close and cur.close >= prev.open


def bearish_engulfing(prev: Candle, cur: Candle) -> bool:
    return prev.close > prev.open and cur.close < cur.open and cur.open >= prev.close and cur.close <= prev.open


def _body_and_range(c: Candle) -> tuple[float, float]:
    return abs(c.close - c.open), c.high - c.low


def hammer(c: Candle) -> bool:
    body, rng = _body_and_range(c)
    if rng <= 0:
        return False
    lower_wick = min(c.open, c.close) - c.low
    upper_wick = c.high - max(c.open, c.close)
    return lower_wick >= 2 * body and upper_wick <= max(body, 0.1 * rng)


def shooting_star(c: Candle) -> bool:
    body, rng = _body_and_range(c)
    if rng <= 0:
        return False
    lower_wick = min(c.open, c.close) - c.low
    upper_wick = c.high - max(c.open, c.close)
    return upper_wick >= 2 * body and lower_wick <= max(body, 0.1 * rng)


TRIGGERS = ("engulfing", "wick", "breakout")  # generic names; each maps to a bullish and a bearish form


def technical_vote(
    candles: Sequence[Candle],
    wanted: Action,
    trend_window: int = 20,
    breakout_window: int = 10,
    triggers: Collection[str] = TRIGGERS,
) -> GateVote:
    """Confirm `wanted` (BUY/SELL) only when the trend agrees AND an enabled trigger pattern fires."""
    if wanted not in (Action.BUY, Action.SELL):
        return GateVote("technical", False, reason="nothing to confirm")
    need = max(trend_window, breakout_window + 1)
    if len(candles) < need:
        return GateVote("technical", False, reason=f"need {need} candles, have {len(candles)}")

    closes = [c.close for c in candles]
    cur, prev = candles[-1], candles[-2]
    trend = sma(closes, trend_window)
    prior = candles[-breakout_window - 1 : -1]

    if wanted == Action.BUY:
        trend_ok = cur.close > trend
        checks = {
            "engulfing": ("bullish_engulfing", bullish_engulfing(prev, cur)),
            "wick": ("hammer", hammer(cur)),
            "breakout": ("breakout", cur.close > max(c.high for c in prior)),
        }
    else:
        trend_ok = cur.close < trend
        checks = {
            "engulfing": ("bearish_engulfing", bearish_engulfing(prev, cur)),
            "wick": ("shooting_star", shooting_star(cur)),
            "breakout": ("breakdown", cur.close < min(c.low for c in prior)),
        }

    fired = [label for key, (label, hit) in checks.items() if hit and key in triggers]
    details = {"sma": round(trend, 4), "close": cur.close, "triggers": fired}
    if not trend_ok:
        return GateVote("technical", False, reason="trend does not confirm", details=details)
    if not fired:
        return GateVote("technical", False, reason="no entry trigger yet", details=details)
    return GateVote("technical", True, action=wanted, reason="+".join(fired), details=details)
