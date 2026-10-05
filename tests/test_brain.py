"""The brain: signals are written down, checked against what the price did, and turned into scorecards."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

pd = pytest.importorskip("pandas")

from trading_universe.brain import Brain, Signal, close_series, move  # noqa: E402

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def daily(closes: list[float], start: datetime = T0) -> pd.DataFrame:
    idx = pd.date_range(pd.Timestamp(start).tz_convert(None), periods=len(closes), freq="D")
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1.0}, index=idx)


def sig(i: int, direction: int, at: datetime, desk: str = "listings", kind: str = "listing", symbol: str = "SOLUSDT") -> Signal:
    return Signal(f"s{i}", at.isoformat(), "news", desk, kind, symbol, direction, 0.5)


def test_move_uses_only_closes_that_happened():
    closes = close_series(daily([100, 110, 121, 133.1]))  # candle closes at 00:00 the next day
    assert move(closes, T0 + timedelta(days=1, hours=1), timedelta(days=1)) == pytest.approx(0.1)
    assert move(closes, T0 + timedelta(days=4, hours=1), timedelta(days=1)) is None  # not happened yet


def test_signals_are_written_once_and_settled_only_after_three_days(tmp_path):
    b = Brain(tmp_path)
    assert b.record(sig(1, 1, T0 + timedelta(days=1, hours=1)))
    assert not b.record(sig(1, 1, T0 + timedelta(days=1, hours=1)))  # same id again
    assert not b.record(Signal("n", T0.isoformat(), "news", "x", "y", "SOLUSDT", 0, 1.0))  # no direction, nothing to check
    frame = daily([100, 102, 104, 106, 108, 110])
    closes = lambda sym: close_series(frame)  # noqa: E731
    assert b.settle(closes, T0 + timedelta(days=2)) == 0  # 3 days not over yet
    assert b.settle(closes, T0 + timedelta(days=5)) == 1
    assert b.outcomes["s1"]["r3"] == pytest.approx(106 / 100 - 1)  # from the close before the news to 3 closes later
    again = Brain(tmp_path)  # survives a restart
    assert "s1" in again.signals and "s1" in again.outcomes


def zigzag(days: int = 150) -> list[float]:
    """3 days up 2%, 3 days down 2%, repeated: up half the time."""
    out = [100.0]
    for i in range(1, days):
        out.append(out[-1] * (1.02 if (i - 1) % 6 < 3 else 0.98))
    return out


def test_scorecard_rewards_signals_that_beat_the_base_rate():
    b = Brain()
    closes = zigzag()
    for k in range(0, 140, 6):  # k = the close before an up-leg; k + 3 = before a down-leg
        for j, (good, bad) in enumerate(((1, -1), (-1, 1))):
            at = T0 + timedelta(days=k + 3 * j + 1, hours=1)
            b.record(sig(10 * k + j, good, at, desk="listings", kind="listing"))
            b.record(sig(10 * k + j + 5, bad, at, desk="regulatory", kind="regulatory"))
    b.settle(lambda s: close_series(daily(closes)), T0 + timedelta(days=149))
    rows = {r["desk"]: r for r in b.scorecard()}
    assert rows["listings"]["hit_rate"] == 1.0 and rows["regulatory"]["hit_rate"] == 0.0
    assert rows["listings"]["base_rate"] == pytest.approx(0.5, abs=0.05) and rows["listings"]["edge"] > 0.45
    assert b.weight("news", "listings", "listing") > 1.3 and b.weight("news", "regulatory", "regulatory") < 0.7
    assert b.weight("news", "macro", "macro") == 1.0  # nothing learned yet


def test_a_rising_market_is_not_mistaken_for_skill():
    b = Brain()
    up = [100 * 1.01 ** i for i in range(80)]
    for i in range(40):
        b.record(sig(i, 1, T0 + timedelta(days=i + 1, hours=1)))
    b.settle(lambda s: close_series(daily(up)), T0 + timedelta(days=79))
    (row,) = b.scorecard()
    assert row["hit_rate"] == 1.0 and row["base_rate"] == 1.0 and row["edge"] == 0.0 and row["weight"] == 1.0


def test_freeze_stops_learning():
    b = Brain()
    closes = zigzag(100)
    for k in range(0, 24, 6):
        b.record(sig(k, 1, T0 + timedelta(days=k + 1, hours=1)))
    b.settle(lambda s: close_series(daily(closes)), T0 + timedelta(days=30))
    before = b.weight("news", "listings", "listing")
    b.freeze(T0 + timedelta(days=30))
    for k in range(30, 90, 6):
        b.record(sig(k, -1, T0 + timedelta(days=k + 1, hours=1)))  # wrong every time: would pull the weight down
    b.settle(lambda s: close_series(daily(closes)), T0 + timedelta(days=99))
    assert len(b.outcomes) > 4
    assert b.weight("news", "listings", "listing") == before


def test_research_cycle_feeds_the_brain_from_all_three_sections(tmp_path):
    from trading_universe.market import CandleFeed
    from trading_universe.news.models import NewsItem
    from trading_universe.runner import RunConfig, Runner

    now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    close = [100 * 1.01 ** i for i in range(300)]
    frame = daily(close, now - timedelta(days=300))
    feed = CandleFeed()
    for s in ("BTCUSDT", "SOLUSDT"):
        feed.put(s, frame)

    class News:
        name = "static"

        def fetch(self):
            return [NewsItem.make("binance", "Binance will list Solana (SOL) perpetuals", "https://x/1", now - timedelta(hours=1),
                                  kind="announcement")]

    r = Runner(RunConfig(data_dir=tmp_path, symbols=("BTCUSDT", "SOLUSDT")), feed=feed, sources=[News()])
    r.research(now)
    sections = {s.section for s in r.orchestrator.brain.signals.values()}
    assert sections == {"news", "price", "risk"}
    kinds = {(s.desk, s.kind) for s in r.orchestrator.brain.signals.values()}
    assert ("trend", "above_averages") in kinds and ("mood", "market_rising") in kinds and ("listings", "listing") in kinds
    r.research(now + timedelta(minutes=15))
    n = len(r.orchestrator.brain.signals)  # same day: nothing written twice
    r.research(now + timedelta(minutes=30))
    assert len(r.orchestrator.brain.signals) == n
    board = json.loads((tmp_path / "agents.json").read_text())["agents"]
    assert "SOL above averages" in board["price:trend"]["doing"] and "whole market rising" in board["risk:mood"]["doing"]
    assert board["brain"]["doing"].startswith(f"{n} signals")

    # The website reads the same files.
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from trading_universe.api import server

    import os
    os.environ["TU_RUNS_DIR"] = str(tmp_path)
    os.environ.pop("TU_PASSWORD", None)
    data = TestClient(server.create_app()).get("/api/brain").json()
    assert data["summary"]["signals"] == n and data["summary"]["settled"] == 0 and data["time_machine"] is None
