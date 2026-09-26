"""Get candles: download from Binance, load a CSV, or generate fake ones for tests and demos."""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]


BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"  # public market data, no API key needed


def _epoch_to_datetime(values: pd.Series) -> pd.DatetimeIndex:
    v = values.astype("int64")
    unit = "us" if v.iloc[0] > 1e14 else "ms"  # Binance bulk files switched to microseconds in 2025
    return pd.DatetimeIndex(pd.to_datetime(v, unit=unit))


def _from_klines(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame([r[:6] for r in rows], columns=["open_time", *COLUMNS])
    df.index = _epoch_to_datetime(df["open_time"])
    df = df[COLUMNS].astype(float).sort_index()
    return df[~df.index.duplicated(keep="last")]


def fetch_binance(symbol: str, interval: str = "1d", start: str = "2020-01-01", end: str | None = None, base_url: str = BINANCE_URL) -> pd.DataFrame:
    """Download spot candles (e.g. BTCUSDT, 1d / 4h / 1h) from Binance's public data API."""
    start_ms = int(pd.Timestamp(start).timestamp() * 1000)
    end_ms = int(pd.Timestamp(end).timestamp() * 1000) if end else int(time.time() * 1000)
    rows: list[list] = []
    while start_ms < end_ms:
        url = f"{base_url}?symbol={symbol.upper()}&interval={interval}&startTime={start_ms}&endTime={end_ms}&limit=1000"
        with urllib.request.urlopen(url, timeout=30) as resp:
            batch = json.loads(resp.read())
        if not batch:
            break
        rows += batch
        if len(batch) < 1000:  # last page
            break
        start_ms = batch[-1][0] + 1
        time.sleep(0.2)  # stay well under Binance's rate limit
    if not rows:
        raise ValueError(f"no candles returned for {symbol} {interval}")
    return _from_klines(rows)


def save_csv(df: pd.DataFrame, path: str | Path) -> None:
    out = df.copy()
    out.index.name = "date"
    out.to_csv(path)


def load_csv(path: str | Path) -> pd.DataFrame:
    """CSV of candles. Accepts a file with a date column plus open/high/low/close[/volume] (any
    capitalisation, e.g. saved by this tool or exported from an exchange), or a raw headerless
    Binance bulk file from data.binance.vision."""
    first = Path(path).read_text().split("\n", 1)[0].split(",")[0].strip()
    if first.isdigit():
        return _from_klines(pd.read_csv(path, header=None).values.tolist())
    df = pd.read_csv(path)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    date_col = next((c for c in ("date", "datetime", "timestamp", "time") if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"{path}: no date column found")
    if "close" not in df.columns and "adj_close" in df.columns:
        df["close"] = df["adj_close"]
    missing = {"open", "high", "low", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df.index = pd.to_datetime(df[date_col], utc=True).dt.tz_localize(None)
    df = df[COLUMNS].astype(float).sort_index()
    return df[~df.index.duplicated(keep="last")].dropna()


def synthetic_prices(days: int = 5 * 365, seed: int = 0, start: float = 1000.0, drift: float = 0.0003, vol: float = 0.015, start_date: str = "2020-01-01", calendar: str = "24/7") -> pd.DataFrame:
    """Random-walk daily candles. Useful for tests, never for real decisions."""
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(drift, vol, days)))
    open_ = np.concatenate([[start], close[:-1]]) * (1 + rng.normal(0, vol / 4, days))
    spread = np.abs(rng.normal(0, vol / 2, days)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    # Crypto trades every day; stock markets only on weekdays.
    idx = pd.date_range(start_date, periods=days, freq="D") if calendar == "24/7" else pd.bdate_range(start_date, periods=days)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": rng.integers(1e5, 1e6, days)}, index=idx)
