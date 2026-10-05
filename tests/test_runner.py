from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

pd = pytest.importorskip("pandas")

from trading_universe.backtest.data import synthetic_prices  # noqa: E402
from trading_universe.market import CandleFeed  # noqa: E402
from trading_universe.news.models import NewsItem  # noqa: E402
from trading_universe.runner import RunConfig, Runner  # noqa: E402


def rising(days: int, end: datetime) -> pd.DataFrame:
    """Steady uptrend where every day closes at a new high (a fresh breakout each day)."""
    close = pd.Series([100 * 1.01**i for i in range(days)])
    open_ = close / 1.005
    df = pd.DataFrame({"open": open_, "high": close, "low": open_ * 0.998, "close": close, "volume": 1.0})
    df.index = pd.date_range(end=pd.Timestamp(end).tz_convert(None).normalize(), periods=days, freq="D")
    return df


class StaticNews:
    name = "static"

    def __init__(self, items):
        self.items = items

    def fetch(self):
        return self.items


def test_end_to_end_news_to_trade_to_lesson(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    feed = CandleFeed()
    for sym in ("BTCUSDT", "SOLUSDT"):
        feed.put(sym, rising(300, now))
    news = StaticNews([NewsItem.make("binance", "Binance Will List Solana (SOL) perpetual contracts", "https://x.test/1",
                                     now - timedelta(hours=1), "", "announcement")])
    r = Runner(RunConfig(data_dir=tmp_path, symbols=("BTCUSDT", "SOLUSDT")), feed=feed, sources=[news])

    r.research(now)
    assert r.trade(now).of("opened") == []  # trading is off until the owner switches it on (brain first)
    assert not r.status.trading_on
    (tmp_path / "settings.json").write_text(json.dumps({"trading_enabled": True}))
    snap = r.snapshots.latest()["SOLUSDT"]
    assert snap.news and snap.news.actionable and "market_downtrend" not in snap.risk_flags

    rep = r.trade(now)
    assert [e.symbol for e in rep.of("opened")] == ["SOLUSDT"]
    (trade,) = r.trade_log.open_trades()
    assert trade.risk_amount * r.agent_cfg.risk.quote_to_inr <= 300  # the ₹ budget holds in USDT terms

    # price collapses through the stop -> trade closes -> mistake loop records the outcome
    df = feed.frame("SOLUSDT").copy()
    last = df.index[-1] + pd.Timedelta(days=1)
    df.loc[last] = [trade.stop_price * 1.01, trade.stop_price * 1.01, trade.stop_price * 0.9, trade.stop_price * 0.92, 1.0]
    feed.put("SOLUSDT", df)
    later = now + timedelta(days=1)
    rep = r.trade(later)
    assert rep.of("closed")
    assert r.memory.events.get(f"trade:{trade.trade_id}") is not None
    status = (tmp_path / "status.json").read_text()
    assert '"trade_ticks": 3' in status and "SOLUSDT opened" in status

    # restart from disk: paper account and trade log survive
    r2 = Runner(RunConfig(data_dir=tmp_path, symbols=("BTCUSDT", "SOLUSDT")), feed=feed, sources=[])
    assert r2.trade_log.closed_trades()[0].trade_id == trade.trade_id
    assert r2.broker.cash() == pytest.approx(r.broker.cash())


def test_status_counters_survive_a_restart(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    feed = CandleFeed()
    feed.put("BTCUSDT", rising(300, now))
    r = Runner(RunConfig(data_dir=tmp_path, symbols=("BTCUSDT",)), feed=feed, sources=[])
    r.trade(now)
    r.trade(now)
    r2 = Runner(RunConfig(data_dir=tmp_path, symbols=("BTCUSDT",)), feed=feed, sources=[])
    assert r2.status.trade_ticks == 2


def falling(days: int, end: datetime) -> pd.DataFrame:
    """Steady downtrend where every day closes at a new low (a fresh breakdown each day)."""
    close = pd.Series([100 * 0.99**i for i in range(days)])
    open_ = close * 1.005
    df = pd.DataFrame({"open": open_, "high": open_ * 1.002, "low": close, "close": close, "volume": 1.0})
    df.index = pd.date_range(end=pd.Timestamp(end).tz_convert(None).normalize(), periods=days, freq="D")
    return df


def test_short_selling_switched_on_from_the_website(tmp_path):
    import json

    now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    feed = CandleFeed()
    for sym in ("BTCUSDT", "SOLUSDT"):
        feed.put(sym, falling(300, now))
    news = StaticNews([NewsItem.make("coindesk", "SEC sues Solana (SOL) foundation, charges fraud", "https://x/sol",
                                     now - timedelta(hours=1), kind="announcement")])
    base = {"trading_enabled": True, "trend_window": 20, "breakout_window": 10, "triggers": ["engulfing", "wick", "breakout"], "stop_loss_pct": 0.03}

    (tmp_path / "settings.json").write_text(json.dumps(base))  # shorts off (the default)
    r = Runner(RunConfig(data_dir=tmp_path, symbols=("BTCUSDT", "SOLUSDT")), feed=feed, sources=[news])
    r.research(now)
    rep = r.trade(now)
    assert not r.status.shorts and any("short selling disabled" in e.detail for e in rep.events)

    (tmp_path / "settings.json").write_text(json.dumps({**base, "allow_short": True}))
    r = Runner(RunConfig(data_dir=tmp_path, symbols=("BTCUSDT", "SOLUSDT")), feed=feed, sources=[news])
    r.research(now)
    rep = r.trade(now)
    assert r.status.shorts and r.status.market_downtrend
    assert [e.symbol for e in rep.events if e.kind == "opened"] == ["SOLUSDT"]
    assert r.broker.positions()["SOLUSDT"] < 0

    # Binance spot can't short, so the switch is ignored there.
    (tmp_path / "status.json").unlink()
    with pytest.raises(Exception):  # no Binance keys here; the point is it never gets as far as shorting
        Runner(RunConfig(data_dir=tmp_path, broker="binance-testnet"), feed=feed, sources=[])
