"""The context block the decision model sees. Built the same way for training data and live trading,
so the model never gets features at trade time that it wasn't trained on."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..models import Candle, Snapshot


def price_features(candles: Sequence[Candle]) -> dict[str, Any]:
    closes = [c.close for c in candles]
    if len(closes) < 21:
        return {"history_days": len(closes)}
    last = closes[-1]

    def sma(n: int) -> float | None:
        return sum(closes[-n:]) / n if len(closes) >= n else None

    rets = [closes[i] / closes[i - 1] - 1 for i in range(max(1, len(closes) - 20), len(closes))]
    mean = sum(rets) / len(rets)
    vol = (sum((r - mean) ** 2 for r in rets) / len(rets)) ** 0.5
    out: dict[str, Any] = {
        "momentum_5d": round(last / closes[-6] - 1, 4),
        "momentum_20d": round(last / closes[-21] - 1, 4),
        "volatility_20d": round(vol, 4),
        "last_candle": "up" if candles[-1].close >= candles[-1].open else "down",
    }
    for n in (20, 50, 200):
        m = sma(n)
        if m:
            out[f"vs_sma{n}"] = round(last / m - 1, 4)
    return out


def decision_context(snapshot: Snapshot | None, candles: Sequence[Candle], symbol: str) -> dict[str, Any]:
    ctx: dict[str, Any] = {"symbol": symbol, "price": price_features(candles)}
    if snapshot is not None:
        ctx.update({
            "sector": snapshot.sector,
            "research_bias": snapshot.direction_bias.value,
            "research_confidence": snapshot.confidence,
            "risk_flags": list(snapshot.risk_flags),
        })
        if snapshot.news is not None:
            ctx["news"] = {
                "direction": snapshot.news.direction.value,
                "magnitude": snapshot.news.magnitude,
                "confidence": snapshot.news.confidence,
                "event_type": snapshot.news.event_type,
                "actionable": snapshot.news.actionable,
                "headline": snapshot.news.headline,
            }
    return ctx
