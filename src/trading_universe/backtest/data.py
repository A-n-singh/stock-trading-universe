"""Load daily candles from CSV, or generate fake ones for tests and demos."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]


def load_csv(path: str | Path) -> pd.DataFrame:
    """CSV with a date column plus open/high/low/close[/volume] (any capitalisation, e.g. a Yahoo export)."""
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


def synthetic_prices(days: int = 5 * 252, seed: int = 0, start: float = 1000.0, drift: float = 0.0003, vol: float = 0.015, start_date: str = "2020-01-01") -> pd.DataFrame:
    """Random-walk daily candles. Useful for tests, never for real decisions."""
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(drift, vol, days)))
    open_ = np.concatenate([[start], close[:-1]]) * (1 + rng.normal(0, vol / 4, days))
    spread = np.abs(rng.normal(0, vol / 2, days)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    idx = pd.bdate_range(start_date, periods=days)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": rng.integers(1e5, 1e6, days)}, index=idx)
