"""The time machine: replays the past day by day without peeking, learns, then sits an exam."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

pd = pytest.importorskip("pandas")

from trading_universe.news.models import NewsItem  # noqa: E402
from trading_universe.time_machine import ArchiveNews, AsOfFeed, TimeMachineConfig, load_archive, replay  # noqa: E402

T0 = datetime(2021, 1, 1, tzinfo=timezone.utc)


def daily(closes: list[float], start: datetime = T0) -> pd.DataFrame:
    idx = pd.date_range(pd.Timestamp(start).tz_convert(None), periods=len(closes), freq="D")
    c = pd.Series(closes, index=idx)
    return pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1.0})


def test_archive_reads_common_formats(tmp_path):
    csv = tmp_path / "a.csv"
    pd.DataFrame({"published_on": [int((T0 + timedelta(hours=5)).timestamp())], "title": ["Binance will list Solana (SOL)"],
                  "body": ["more text"], "url": ["https://x/1"], "source": ["coindesk"]}).to_csv(csv, index=False)
    (item,) = load_archive(csv)
    assert item.published == T0 + timedelta(hours=5) and item.symbols == ("SOLUSDT",) and item.event_type == "listing"

    dates_only = tmp_path / "b.csv"
    pd.DataFrame({"datetime": ["2021-01-01", "2021-01-02"], "text": ["sec sues exchange over bitcoin", "ethereum upgrade"]}).to_csv(dates_only, index=False)
    a, b = load_archive(dates_only)
    assert a.published == T0 + timedelta(days=1, seconds=-1)  # known at the end of that day, never earlier
    assert a.event_type == "regulatory" and b.symbols == ("ETHUSDT",)

    pq = tmp_path / "c.parquet"
    pd.DataFrame({"published_on": [T0], "title": ["Bitcoin ETF approved"]}).to_parquet(pq)
    assert load_archive(pq)[0].event_type == "etf"


def test_news_window_and_closed_candles_only():
    items = [NewsItem.make("x", f"Bitcoin news {i}", f"https://x/{i}", T0 + timedelta(hours=i)) for i in range(10)]
    store = ArchiveNews(items)
    got = store.items(since=T0 + timedelta(hours=2), until=T0 + timedelta(hours=4))
    assert [i.title for i in got] == ["Bitcoin news 4", "Bitcoin news 3", "Bitcoin news 2"]

    feed = AsOfFeed({"BTCUSDT": daily([100, 101, 102, 103])})
    feed.now = T0 + timedelta(days=2, minutes=5)  # the candles of day 0 and day 1 have closed, day 2's is still forming
    assert len(feed.frame("BTCUSDT")) == 2 and feed.last_close("BTCUSDT") == 101
    assert len(feed.candles("BTCUSDT")) == 2
    feed.now = T0
    with pytest.raises(KeyError):
        feed.frame("BTCUSDT")
    assert feed.candles("BTCUSDT") == [] and feed.candles("SOLUSDT") == []


def test_replay_learns_then_sits_the_exam(tmp_path):
    # Prices that rise for 3 days after every "listing" headline and drift otherwise.
    days = 520
    closes, news, p = [], [], 100.0
    for d in range(days):
        if d % 10 in (1, 2, 3):
            p *= 1.03
        else:
            p *= 0.995 if d % 2 else 1.004
        closes.append(p)
        if d % 10 == 0 and d > 0:
            news.append(NewsItem.make("x", f"Binance will list Solana (SOL) product {d}", f"https://x/{d}",
                                      T0 + timedelta(days=d, hours=23)))
    frames = {"BTCUSDT": daily(closes), "SOLUSDT": daily(closes)}
    cfg = TimeMachineConfig(symbols=("BTCUSDT", "SOLUSDT"), start=T0 + timedelta(days=210), exam_days=120)
    rep = replay(cfg, frames, news, tmp_path, progress=lambda s: None)

    assert rep["days"] == pytest.approx(days - 210, abs=2)
    assert rep["news_items"] > 0 and rep["signals"] > 0
    learned = {(r["desk"], r["kind"]): r for r in rep["learned"]}
    assert learned[("listings", "listing")]["hit_rate"] == 1.0 and learned[("listings", "listing")]["weight"] > 1.0
    exam = {(r["desk"], r["kind"]): r for r in rep["exam"]}
    assert exam[("listings", "listing")]["signals"] >= 8
    assert rep["exam_summary"]["signals"] == sum(r["signals"] for r in rep["exam"])
    assert set(rep["trades"]) == {"trades", "won", "total_r", "profit_inr", "hold_r"}
    assert json.loads((tmp_path / "report.json").read_text())["exam_summary"] == rep["exam_summary"]

    # No peeking: every checked signal was known before the price moves it was checked against.
    signals = [json.loads(line) for line in (tmp_path / "brain" / "signals.jsonl").read_text().splitlines()]
    cutoff = datetime.fromisoformat(rep["period"]["cutoff"])
    assert any(datetime.fromisoformat(s["at"]) >= cutoff for s in signals)
    news_at = {s["at"] for s in signals if s["section"] == "news"}
    assert news_at <= {i.published.isoformat() for i in news}


def test_replay_starts_with_an_empty_brain(tmp_path):
    frames = {"BTCUSDT": daily([100 * 1.001 ** i for i in range(400)])}
    cfg = TimeMachineConfig(symbols=("BTCUSDT",), start=T0 + timedelta(days=210), exam_days=60, trades=False)
    first = replay(cfg, frames, [], tmp_path, progress=lambda s: None)
    second = replay(cfg, frames, [], tmp_path, progress=lambda s: None)
    assert first["signals"] == second["signals"] and second["trades"] is None
    with pytest.raises(ValueError):
        replay(TimeMachineConfig(symbols=("BTCUSDT",), start=T0 + timedelta(days=380), exam_days=10), frames, [], tmp_path)
