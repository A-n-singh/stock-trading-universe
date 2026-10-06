"""Daily stop: no new trades for the rest of the day once the day's losses reach the limit."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from trading_universe.trading_agent.safety import DailyStop

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def test_daily_stop_trips_at_the_limit_and_resets_the_next_day():
    ds = DailyStop(0.02)
    assert not ds.check(1000, NOW)  # the day starts at 1000
    assert not ds.check(985, NOW + timedelta(hours=1))  # -1.5%
    assert ds.check(979, NOW + timedelta(hours=2))  # -2.1%: stopped
    assert ds.check(1005, NOW + timedelta(hours=3))  # stays stopped for the rest of the day
    assert not ds.check(1005, NOW + timedelta(days=1))  # new day, new start
    again = DailyStop.restore(json.loads(json.dumps(ds.state())), 0.02)
    assert again.start_equity == 1005 and again.day == (NOW + timedelta(days=1)).date().isoformat()


def test_runner_opens_nothing_while_the_daily_stop_is_on(tmp_path):
    pytest.importorskip("pandas")
    from test_control import runner  # same small world as the Agents-page tests

    from trading_universe.news.models import NewsItem

    (tmp_path / "settings.json").write_text(json.dumps({"trading_enabled": True}))
    item = NewsItem.make("binance", "Binance will list Solana (SOL) perpetuals", "https://x/l", NOW - timedelta(hours=1), kind="announcement")
    r = runner(tmp_path, [item])
    r.research(NOW)
    r.agent.daily_stop = DailyStop(0.02, day=NOW.date().isoformat(), start_equity=10_000)  # the day started much higher
    rep = r.trade(NOW)
    assert rep.of("halted") and not rep.of("opened")
    board = json.loads((tmp_path / "agents.json").read_text())["agents"]["trading"]
    assert board["status"] == "paused" and board["doing"].startswith("Daily stop")
    saved = json.loads((tmp_path / "daily_stop.json").read_text())
    assert saved["tripped_at"] == NOW.isoformat() and json.loads((tmp_path / "status.json").read_text())["daily_stop"]["tripped_at"]

    r2 = runner(tmp_path, [item])  # a restart keeps the stop for the rest of the day
    assert r2.agent.daily_stop.tripped_at == NOW.isoformat()
    rep = r2.trade(NOW + timedelta(days=1))  # next day: trading allowed again
    assert not rep.of("halted")
