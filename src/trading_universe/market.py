"""Recent candles for the research loop and the Trading Agent, refreshed on a timer."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from .models import Candle

Fetcher = Callable[[str, str, str], pd.DataFrame]  # (symbol, interval, start) -> OHLCV frame


def _default_fetcher(symbol: str, interval: str, start: str) -> pd.DataFrame:
    from .backtest.data import fetch_binance

    return fetch_binance(symbol, interval, start)


@dataclass
class CandleFeed:
    interval: str = "1d"
    lookback_days: int = 400
    ttl_s: float = 300.0
    fetcher: Fetcher = _default_fetcher
    clock: Callable[[], float] = time.time
    _cache: dict[str, tuple[float, pd.DataFrame]] = field(default_factory=dict)

    def frame(self, symbol: str) -> pd.DataFrame:
        hit = self._cache.get(symbol)
        if hit and self.clock() - hit[0] < self.ttl_s:
            return hit[1]
        start = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=self.lookback_days)).strftime("%Y-%m-%d")
        df = self.fetcher(symbol, self.interval, start)
        self._cache[symbol] = (self.clock(), df)
        return df

    def candles(self, symbol: str) -> list[Candle]:
        """MarketData protocol for the Trading Agent. Missing data -> empty list (the agent then skips)."""
        try:
            df = self.frame(symbol)
        except Exception:
            return []
        return [Candle(ts.to_pydatetime(), r.open, r.high, r.low, r.close, r.volume) for ts, r in zip(df.index, df.itertuples())]

    def put(self, symbol: str, df: pd.DataFrame) -> None:
        """Seed the cache (tests, replays)."""
        self._cache[symbol] = (float("inf"), df)
