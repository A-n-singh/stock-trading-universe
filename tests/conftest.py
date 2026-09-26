from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from trading_universe.config import AgentConfig
from trading_universe.execution.broker import PaperBroker
from trading_universe.execution.resilient import ResilientExecutor, TokenBucket
from trading_universe.models import Candle, Direction, NewsSignal, Snapshot
from trading_universe.trade_log import TradeLog
from trading_universe.trading_agent.agent import TradingAgent

# Tests never download the free news model (hundreds of MB); tests that need it pass a fake one.
os.environ["TU_NEWS_MODEL"] = "off"
for _k in ("TU_LLM_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
    os.environ.pop(_k, None)

NOW = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


def uptrend(n: int = 25, start: float = 100.0, step: float = 1.0) -> list[Candle]:
    out = []
    for i in range(n):
        close = start + i * step
        o = close - 0.5
        out.append(Candle(NOW - timedelta(minutes=n - i), o, close + 0.2, o - 0.2, close, 1000))
    return out


def flat(n: int = 25, price: float = 100.0) -> list[Candle]:
    return [Candle(NOW - timedelta(minutes=n - i), price, price + 0.1, price - 0.1, price, 1000) for i in range(n)]


def snapshot(
    symbol: str = "BTCUSDT",
    *,
    as_of: datetime = NOW,
    bias: Direction = Direction.BULLISH,
    confidence: float = 0.8,
    actionable: bool = True,
    risk_flags: tuple[str, ...] = (),
    event_type: str = "listing",
    sector: str = "layer1",
    snapshot_id: str = "s1",
) -> Snapshot:
    return Snapshot(
        symbol=symbol,
        direction_bias=bias,
        confidence=confidence,
        as_of=as_of,
        sector=sector,
        risk_flags=risk_flags,
        news=NewsSignal(bias, magnitude=0.7, confidence=0.8, event_type=event_type, actionable=actionable),
        rationale="listed on a major exchange",
        snapshot_id=snapshot_id,
    )


class Market:
    def __init__(self, data: dict[str, list[Candle]] | None = None) -> None:
        self.data = data or {}

    def candles(self, symbol: str) -> list[Candle]:
        return self.data.get(symbol, [])


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def broker() -> PaperBroker:
    return PaperBroker(starting_cash=100_000, slippage_bps=0, fee_bps=0)


@pytest.fixture
def agent(broker: PaperBroker) -> TradingAgent:
    clock = FakeClock()
    ex = ResilientExecutor(broker, limiter=TokenBucket(100, 100, clock=clock), sleep=lambda s: None, clock=clock)
    return TradingAgent(AgentConfig(), ex, TradeLog())
