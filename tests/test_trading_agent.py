from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from conftest import NOW, Market, flat, snapshot, uptrend
from trading_universe.config import RiskConfig
from trading_universe.models import Action, AssetClass, Candle, Direction
from trading_universe.trading_agent.risk import PortfolioState, risk_vote, size_position


def test_and_gate_opens_trade_when_all_three_agree(agent, broker):
    report = agent.tick({"BTCUSDT": snapshot()}, Market({"BTCUSDT": uptrend()}), NOW)
    assert [e.kind for e in report.events] == ["opened"]
    assert set(broker.positions()) == {"BTCUSDT"} and broker.positions()["BTCUSDT"] > 0
    (rec,) = agent.trade_log.open_trades()
    assert rec.snapshot["rationale"] == "listed on a major exchange"  # mistake-loop: logs what it acted on
    assert {v["name"] for v in rec.votes} == {"news", "technical", "risk"}
    assert 200 <= rec.risk_amount <= 300


def test_stale_or_missing_snapshot_is_skipped(agent, broker):
    stale = snapshot(as_of=NOW - timedelta(hours=1))
    report = agent.tick({"BTCUSDT": stale}, Market({"BTCUSDT": uptrend()}), NOW)
    assert report.of("skipped") and not broker.positions()


def test_confident_news_alone_is_not_enough(agent, broker):
    report = agent.tick({"BTCUSDT": snapshot(confidence=0.99)}, Market({"BTCUSDT": flat()}), NOW)
    assert report.of("watching") and not broker.positions()
    assert agent.watch.get("BTCUSDT") is not None


def test_watch_state_resolves_on_later_technical_confirmation(agent, broker):
    market = Market({"BTCUSDT": flat()})
    agent.tick({"BTCUSDT": snapshot()}, market, NOW)
    # Later: research no longer re-flags the news, but the bias holds and price now confirms.
    later = NOW + timedelta(minutes=30)
    market.data["BTCUSDT"] = uptrend()
    report = agent.tick({"BTCUSDT": snapshot(as_of=later, actionable=False, snapshot_id="s2")}, market, later)
    assert report.of("opened")
    assert agent.watch.get("BTCUSDT") is None


def test_watch_state_ages_out(agent, broker):
    agent.cfg.watch_windows_s[("layer1", "listing")] = 600
    agent.tick({"BTCUSDT": snapshot()}, Market({"BTCUSDT": flat()}), NOW)
    later = NOW + timedelta(minutes=11)
    report = agent.tick({}, Market({"BTCUSDT": flat()}), later)
    assert report.of("expired") and agent.watch.get("BTCUSDT") is None


def test_bias_flip_drops_watched_hypothesis(agent):
    agent.tick({"BTCUSDT": snapshot()}, Market({"BTCUSDT": flat()}), NOW)
    flipped = snapshot(bias=Direction.BEARISH, actionable=False, as_of=NOW + timedelta(minutes=1))
    report = agent.tick({"BTCUSDT": flipped}, Market({"BTCUSDT": flat()}), NOW + timedelta(minutes=1))
    assert report.of("expired") and agent.watch.get("BTCUSDT") is None


def test_blocking_risk_flag_rejects(agent, broker):
    report = agent.tick({"BTCUSDT": snapshot(risk_flags=("halted",))}, Market({"BTCUSDT": uptrend()}), NOW)
    assert report.of("rejected") and not broker.positions()


def test_stop_loss_closes_at_about_the_risk_budget(agent, broker):
    market = Market({"BTCUSDT": uptrend()})
    agent.tick({"BTCUSDT": snapshot()}, market, NOW)
    (rec,) = agent.trade_log.open_trades()
    crash = Candle(NOW + timedelta(minutes=1), rec.stop_price + 0.5, rec.stop_price + 0.6, rec.stop_price - 5, rec.stop_price - 4)
    market.data["BTCUSDT"] = market.data["BTCUSDT"] + [crash]
    report = agent.tick({}, market, NOW + timedelta(minutes=1))
    assert report.of("closed")
    (closed,) = agent.trade_log.closed_trades()
    assert closed.exit_reason == "stop_loss"
    assert closed.pnl == pytest.approx(-closed.risk_amount)
    assert broker.positions() == {}


def test_reversal_snapshot_exits(agent, broker):
    market = Market({"BTCUSDT": uptrend()})
    agent.tick({"BTCUSDT": snapshot()}, market, NOW)
    bear = snapshot(bias=Direction.BEARISH, as_of=NOW + timedelta(minutes=1), snapshot_id="s2")
    report = agent.tick({"BTCUSDT": bear}, market, NOW + timedelta(minutes=1))
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
    # One share of a ₹50,000 stock with a 2% stop risks ₹1,000 > budget (stocks can't be bought in fractions).
    snap = replace(snapshot(), asset_class=AssetClass.STOCK)
    vote = risk_vote(snap, Action.BUY, 50_000, PortfolioState(1e7, 1e7, {}), RiskConfig())
    assert not vote.approve


def test_crypto_allows_fractional_size():
    snap = replace(snapshot(), asset_class=AssetClass.CRYPTO)
    vote = risk_vote(snap, Action.BUY, 5_000_000, PortfolioState(1e7, 1e7, {}), RiskConfig())
    assert vote.approve and 0 < vote.details["quantity"] < 1


def test_short_disabled_by_default():
    snap = snapshot(bias=Direction.BEARISH)
    assert not risk_vote(snap, Action.SELL, 100, PortfolioState(1e5, 1e5, {}), RiskConfig()).approve


def test_rupee_budget_is_converted_for_usdt_prices():
    # BTC at 84,000 USDT, 2% stop, ₹250 budget, 1 USDT = ₹88: risk ≈ 2.84 USDT, not 250 USDT.
    cfg = RiskConfig(risk_per_trade=250, quote_to_inr=88.0)
    vote = risk_vote(snapshot(), Action.BUY, 84_000, PortfolioState(10_000, 10_000, {}), cfg)
    assert vote.approve
    assert vote.details["risk_amount"] == pytest.approx(250 / 88, rel=0.01)
    assert vote.details["risk_inr"] <= 250 + 1e-6
    assert vote.details["quantity"] * 84_000 < 200  # position of ~$142, not ~$12,500


# ---------------------------------------------------------------- short selling (roadmap step 2)


def _short_agent(broker):
    from conftest import FakeClock
    from trading_universe.config import AgentConfig
    from trading_universe.execution.resilient import ResilientExecutor, TokenBucket
    from trading_universe.trade_log import TradeLog
    from trading_universe.trading_agent.agent import TradingAgent

    clock = FakeClock()
    ex = ResilientExecutor(broker, limiter=TokenBucket(100, 100, clock=clock), sleep=lambda s: None, clock=clock)
    return TradingAgent(AgentConfig(risk=RiskConfig(allow_short=True)), ex, TradeLog())


def _bear(**kw):
    kw.setdefault("risk_flags", ("market_downtrend",))
    return snapshot(bias=Direction.BEARISH, event_type="hack", **kw)


def test_short_opens_in_a_falling_market_and_stop_loss_caps_the_loss(broker):
    agent = _short_agent(broker)
    market = Market({"BTCUSDT": uptrend(step=-1.0, start=200)})
    report = agent.tick({"BTCUSDT": _bear()}, market, NOW)
    assert [e.kind for e in report.events] == ["opened"]
    assert broker.positions()["BTCUSDT"] < 0
    (rec,) = agent.trade_log.open_trades()
    assert rec.action == Action.SELL.value and rec.stop_price > rec.entry_price
    assert 200 <= rec.risk_amount <= 300
    spike = Candle(NOW + timedelta(minutes=1), rec.stop_price - 0.5, rec.stop_price + 5, rec.stop_price - 0.6, rec.stop_price + 4)
    market.data["BTCUSDT"] = market.data["BTCUSDT"] + [spike]
    agent.tick({}, market, NOW + timedelta(minutes=1))
    (closed,) = agent.trade_log.closed_trades()
    assert closed.exit_reason == "stop_loss" and closed.pnl == pytest.approx(-closed.risk_amount)
    assert broker.positions() == {}


def test_short_rules():
    cfg = RiskConfig(allow_short=True)
    book = PortfolioState(1e5, 1e5, {})
    sell = lambda snap, pf=book: risk_vote(snap, Action.SELL, 100, pf, cfg)  # noqa: E731
    assert sell(_bear()).approve
    # Only while the whole market is falling; a rising market or wild swings block it.
    assert "market is falling" in sell(_bear(risk_flags=())).reason
    assert not sell(_bear(risk_flags=("market_downtrend", "high_volatility"))).approve
    assert not sell(_bear(risk_flags=("market_uptrend",))).approve
    assert not sell(_bear(risk_flags=("market_downtrend", "hack"))).approve  # safety flags still block
    # The falling-market flag blocks buys, not shorts.
    assert not risk_vote(snapshot(risk_flags=("market_downtrend",)), Action.BUY, 100, book, cfg).approve
    # At most two shorts at once.
    two = PortfolioState(1e5, 1e5, {"ETHUSDT": -1.0, "SOLUSDT": -2.0})
    assert "max open shorts" in sell(_bear(), two).reason
    # No leverage: shorts must stay covered by equity.
    covered = PortfolioState(1_000, 2_000, {"ETHUSDT": -1.0}, short_exposure=1_000)
    assert not sell(_bear(), covered).approve
    # ...and the cash received from shorts can't pay for buys.
    assert not risk_vote(snapshot(), Action.BUY, 100, covered, cfg).approve


def test_paper_broker_short_needs_equity_cover():
    from trading_universe.execution.broker import BrokerError, OrderRequest, PaperBroker

    b = PaperBroker(starting_cash=1_000, slippage_bps=0, fee_bps=0)
    b.place_order(OrderRequest("s1", "ETHUSDT", Action.SELL, 5, 100))  # 500 short against 1,000 equity
    assert b.positions() == {"ETHUSDT": -5} and b.equity() == pytest.approx(1_000)
    with pytest.raises(BrokerError, match="equity"):
        b.place_order(OrderRequest("s2", "SOLUSDT", Action.SELL, 6, 100))  # 500 + 600 > 1,000
    with pytest.raises(BrokerError, match="equity"):
        b.place_order(OrderRequest("b1", "BTCUSDT", Action.BUY, 6, 100))  # 500 short + 600 long > 1,000 own money
    b.mark("ETHUSDT", 80)  # price fell: the short made 100
    assert b.equity() == pytest.approx(1_100)
    b.place_order(OrderRequest("s1:exit", "ETHUSDT", Action.BUY, 5, 80))
    assert b.positions() == {} and b.cash() == pytest.approx(1_100)
