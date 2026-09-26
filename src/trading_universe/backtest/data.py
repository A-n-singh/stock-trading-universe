"""Get candles: download from Binance, load a CSV, or generate fake ones for tests and demos."""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]


# Binance serves the same public candles from several places. The live API refuses some
# regions (e.g. US servers such as Google Colab get HTTP 451), so we fall back to the bulk
# archive at data.binance.vision, which is plain static files and works from anywhere.
BINANCE_API_URLS = (
    "https://data-api.binance.vision/api/v3/klines",  # public market-data mirror, no API key
    "https://api.binance.com/api/v3/klines",
)
BINANCE_BULK_URL = "https://data.binance.vision/data/spot"


def _epoch_to_datetime(values: pd.Series) -> pd.DatetimeIndex:
    v = values.astype("int64")
    # Binance bulk files switched from milliseconds to microseconds in 2025; a download that spans
    # both has mixed units, so convert row by row.
    v = v.where(v < 10**14, v // 1000)
    return pd.DatetimeIndex(pd.to_datetime(v, unit="ms"))


def _from_klines(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame([r[:6] for r in rows], columns=["open_time", *COLUMNS])
    df.index = _epoch_to_datetime(df["open_time"])
    df = df[COLUMNS].astype(float).sort_index()
    return df[~df.index.duplicated(keep="last")]


def _get(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "trading-universe/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_binance_api(symbol: str, interval: str, start: str, end: str | None, base_url: str) -> pd.DataFrame:
    start_ms = int(pd.Timestamp(start).timestamp() * 1000)
    end_ms = int(pd.Timestamp(end).timestamp() * 1000) if end else int(time.time() * 1000)
    rows: list[list] = []
    while start_ms < end_ms:
        url = f"{base_url}?symbol={symbol.upper()}&interval={interval}&startTime={start_ms}&endTime={end_ms}&limit=1000"
        batch = json.loads(_get(url))
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


def fetch_binance_bulk(symbol: str, interval: str, start: str, end: str | None = None, base_url: str = BINANCE_BULK_URL) -> pd.DataFrame:
    """Download from Binance's static archive: one zip per finished month, one per day for the current month."""
    sym = symbol.upper()
    first = pd.Timestamp(start).normalize()
    last = (pd.Timestamp(end) if end else pd.Timestamp.utcnow().tz_localize(None)).normalize()
    this_month = last.replace(day=1)
    urls = [
        f"{base_url}/monthly/klines/{sym}/{interval}/{sym}-{interval}-{m:%Y-%m}.zip"
        for m in pd.date_range(first.replace(day=1), this_month, freq="MS")
        if m < this_month
    ]
    urls += [
        f"{base_url}/daily/klines/{sym}/{interval}/{sym}-{interval}-{d:%Y-%m-%d}.zip"
        for d in pd.date_range(max(this_month, first), last, freq="D")
    ]
    rows: list[list] = []
    for url in urls:
        try:
            blob = _get(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:  # not listed yet that month/day, or today's file not published yet
                continue
            raise
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for name in z.namelist():
                text = z.read(name).decode()
                rows += [line.split(",") for line in text.splitlines() if line and line[0].isdigit()]
    if not rows:
        raise ValueError(f"no candles found for {sym} {interval} in the Binance archive")
    df = _from_klines([[int(r[0]), *r[1:6]] for r in rows])
    df = df[df.index >= first]
    return df[df.index <= last + pd.Timedelta(days=1)] if end else df


def fetch_binance(symbol: str, interval: str = "1d", start: str = "2020-01-01", end: str | None = None, source: str = "auto") -> pd.DataFrame:
    """Download spot candles (e.g. BTCUSDT; 1d / 4h / 1h) from Binance. No account or API key needed.

    source: "auto" tries the live API first and falls back to the bulk archive if the API is
    blocked in this region; "api" or "bulk" force one of them.
    """
    errors = []
    if source in ("auto", "api"):
        for url in BINANCE_API_URLS:
            try:
                return fetch_binance_api(symbol, interval, start, end, url)
            except (urllib.error.URLError, OSError, ValueError) as e:  # 451/403 = region blocked
                errors.append(f"{url}: {e}")
        if source == "api":
            raise ConnectionError("Binance API unreachable:\n" + "\n".join(errors))
    return fetch_binance_bulk(symbol, interval, start, end)


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
