from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from conftest import NOW, Market, flat, snapshot, uptrend
from trading_universe.config import RiskConfig
from trading_universe.models import Action, AssetClass, Candle, Direction
from trading_universe.trading_agent.risk import PortfolioState, risk_vote, size_position


def test_and_gate_opens_trade_when_all_three_agree(agent, broker):
    report = agent.tick({"INFY": snapshot()}, Market({"INFY": uptrend()}), NOW)
    assert [e.kind for e in report.events] == ["opened"]
    assert broker.positions() == {"INFY": 100.0}
    (rec,) = agent.trade_log.open_trades()
    assert rec.snapshot["rationale"] == "beat estimates"  # mistake-loop: logs what it acted on
    assert {v["name"] for v in rec.votes} == {"news", "technical", "risk"}
    assert 200 <= rec.risk_amount <= 300


def test_stale_or_missing_snapshot_is_skipped(agent, broker):
    stale = snapshot(as_of=NOW - timedelta(hours=1))
    report = agent.tick({"INFY": stale}, Market({"INFY": uptrend()}), NOW)
    assert report.of("skipped") and not broker.positions()


def test_confident_news_alone_is_not_enough(agent, broker):
    report = agent.tick({"INFY": snapshot(confidence=0.99)}, Market({"INFY": flat()}), NOW)
    assert report.of("watching") and not broker.positions()
    assert agent.watch.get("INFY") is not None


def test_watch_state_resolves_on_later_technical_confirmation(agent, broker):
    market = Market({"INFY": flat()})
    agent.tick({"INFY": snapshot()}, market, NOW)
    # Later: research no longer re-flags the news, but the bias holds and price now confirms.
    later = NOW + timedelta(minutes=30)
    market.data["INFY"] = uptrend()
    report = agent.tick({"INFY": snapshot(as_of=later, actionable=False, snapshot_id="s2")}, market, later)
    assert report.of("opened")
    assert agent.watch.get("INFY") is None


def test_watch_state_ages_out(agent, broker):
    agent.cfg.watch_windows_s[("it", "earnings")] = 600
    agent.tick({"INFY": snapshot()}, Market({"INFY": flat()}), NOW)
    later = NOW + timedelta(minutes=11)
    report = agent.tick({}, Market({"INFY": flat()}), later)
    assert report.of("expired") and agent.watch.get("INFY") is None


def test_bias_flip_drops_watched_hypothesis(agent):
    agent.tick({"INFY": snapshot()}, Market({"INFY": flat()}), NOW)
    flipped = snapshot(bias=Direction.BEARISH, actionable=False, as_of=NOW + timedelta(minutes=1))
    report = agent.tick({"INFY": flipped}, Market({"INFY": flat()}), NOW + timedelta(minutes=1))
    assert report.of("expired") and agent.watch.get("INFY") is None


def test_blocking_risk_flag_rejects(agent, broker):
    report = agent.tick({"INFY": snapshot(risk_flags=("halted",))}, Market({"INFY": uptrend()}), NOW)
    assert report.of("rejected") and not broker.positions()


def test_stop_loss_closes_at_about_the_risk_budget(agent, broker):
    market = Market({"INFY": uptrend()})
    agent.tick({"INFY": snapshot()}, market, NOW)
    (rec,) = agent.trade_log.open_trades()
    crash = Candle(NOW + timedelta(minutes=1), rec.stop_price + 0.5, rec.stop_price + 0.6, rec.stop_price - 5, rec.stop_price - 4)
    market.data["INFY"] = market.data["INFY"] + [crash]
    report = agent.tick({}, market, NOW + timedelta(minutes=1))
    assert report.of("closed")
    (closed,) = agent.trade_log.closed_trades()
    assert closed.exit_reason == "stop_loss"
    assert closed.pnl == pytest.approx(-closed.risk_amount)
    assert broker.positions() == {}


def test_reversal_snapshot_exits(agent, broker):
    market = Market({"INFY": uptrend()})
    agent.tick({"INFY": snapshot()}, market, NOW)
    bear = snapshot(bias=Direction.BEARISH, as_of=NOW + timedelta(minutes=1), snapshot_id="s2")
    report = agent.tick({"INFY": bear}, market, NOW + timedelta(minutes=1))
    assert report.of("closed")[0].detail.startswith("snapshot_reversal")


def test_risk_budget_is_enforced_by_config():
    for bad in (100, 199.99, 300.01, 1000):
        with pytest.raises(ValueError):
            RiskConfig(risk_per_trade=bad)
    RiskConfig(risk_per_trade=200)
    RiskConfig(risk_per_trade=300)


@pytest.mark.parametrize("price", [1.5, 17.0, 123.45, 2500.0, 49_999.0])
def test_sizing_never_exceeds_budget(price):
    cfg = RiskConfig(risk_per_trade=300)
    qty, risk = size_position(price, price * 0.98, cfg, equity=10_000_000, cash=10_000_000, fractional=False)
    assert risk <= 300 + 1e-9


def test_position_too_expensive_for_budget_is_rejected():
    # One share of a ₹50,000 stock with a 2% stop risks ₹1,000 > budget.
    snap = snapshot()
    vote = risk_vote(snap, Action.BUY, 50_000, PortfolioState(1e7, 1e7, {}), RiskConfig())
    assert not vote.approve


def test_crypto_allows_fractional_size():
    snap = replace(snapshot(), asset_class=AssetClass.CRYPTO)
    vote = risk_vote(snap, Action.BUY, 5_000_000, PortfolioState(1e7, 1e7, {}), RiskConfig())
    assert vote.approve and 0 < vote.details["quantity"] < 1


def test_short_disabled_by_default():
    snap = snapshot(bias=Direction.BEARISH)
    assert not risk_vote(snap, Action.SELL, 100, PortfolioState(1e5, 1e5, {}), RiskConfig()).approve
