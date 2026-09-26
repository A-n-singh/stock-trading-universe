from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

pd = pytest.importorskip("pandas")

from conftest import NOW, Market, snapshot, uptrend  # noqa: E402
from trading_universe.news.models import NewsItem  # noqa: E402
from trading_universe.news.store import NewsStore  # noqa: E402
from trading_universe.training.dataset import examples_from_history, examples_from_snapshots, simulate_long  # noqa: E402
from trading_universe.training.models import ConstantModel, parse_output  # noqa: E402
from trading_universe.training.train import profit_and_calibration_reward  # noqa: E402

ALLOWED = ("buy", "sell", "hold")


def test_parse_output_is_strict_and_safe():
    assert parse_output('blah {"answer": "buy", "confidence": 0.8} blah', ALLOWED) == (parse_output('{"answer":"buy","confidence":0.8}', ALLOWED)[0], True)
    out, ok = parse_output('{"answer": "moon", "confidence": 0.9}', ALLOWED)
    assert (out.answer, out.confidence, ok) == ("hold", 0.0, False)
    assert parse_output('{"answer": "sell", "confidence": 7}', ALLOWED)[0].confidence == 1.0


def test_reward_prefers_profit_honesty_and_valid_format():
    chat = lambda a, c: [{"role": "assistant", "content": f'{{"answer": "{a}", "confidence": {c}}}'}]  # noqa: E731
    r = profit_and_calibration_reward(
        [chat("buy", 0.8), chat("hold", 0.8), [{"role": "assistant", "content": "??"}], chat("buy", 0.95), chat("buy", 0.55)],
        label=["buy", "buy", "buy", "hold", "hold"], pnl_r=[2.0, 2.0, 2.0, -1.0, -1.0], taken_action=["buy"] * 5)
    good, missed, garbage, overconfident_loss, humble_loss = r
    assert good > missed > garbage == -2.0
    assert overconfident_loss < humble_loss


def frame(prices: list[float], start="2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(prices), freq="D")
    s = pd.Series(prices, index=idx)
    return pd.DataFrame({"open": s, "high": s * 1.001, "low": s * 0.999, "close": s, "volume": 1.0})


def test_simulate_long_stop_and_time_exit():
    gap = frame([100, 101, 90, 95])  # opens far below the stop: filled at the open, worse than -1 R
    r, why = simulate_long(gap, 0, 0.03, 3, fee=0)
    assert why == "stop_loss" and r == pytest.approx(-10 / 3, abs=0.01)
    normal = frame([100, 99, 98, 95])
    normal.loc[normal.index[2], "low"] = 96.5  # dips through the 97 stop intraday
    r, why = simulate_long(normal, 0, 0.03, 3, fee=0)
    assert why == "stop_loss" and r == pytest.approx(-1.0, abs=0.01)
    r, why = simulate_long(frame([100, 101, 103, 106]), 0, 0.03, 3, fee=0)
    assert why == "time" and r == pytest.approx(2.0, abs=0.01)


def test_history_examples_use_only_news_public_at_the_time():
    df = frame([100 + i for i in range(40)])
    entries = pd.Series(False, index=df.index)
    entries.iloc[25] = True
    news = NewsStore()
    t = df.index[25].to_pydatetime().replace(tzinfo=timezone.utc)
    news.add(NewsItem.make("t", "Solana record high rally", "u1", t - timedelta(hours=2)))
    news.add(NewsItem.make("t", "Solana hacked, funds stolen", "u2", t + timedelta(hours=2)))  # the future
    (ex,) = examples_from_history({"SOLUSDT": df}, {"SOLUSDT": entries}, news)
    assert ex.context["news"]["headline"] == "Solana record high rally"
    assert ex.output.answer == "buy" and ex.meta["pnl"] > 0


def test_snapshot_examples_skip_when_the_future_is_unknown():
    df = frame([100 + i for i in range(40)])
    early = snapshot("SOLUSDT", as_of=datetime(2024, 1, 25, 12, tzinfo=timezone.utc))
    late = snapshot("SOLUSDT", as_of=datetime(2024, 2, 8, 12, tzinfo=timezone.utc))  # < 10 days of data after it
    exs = examples_from_snapshots([early, late], {"SOLUSDT": df})
    assert len(exs) == 1 and exs[0].context["research_bias"] == "bullish"


def test_decision_model_is_a_fourth_check(agent, broker):
    agent.decision_model = ConstantModel("hold", 0.9)
    rep = agent.tick({"BTCUSDT": snapshot()}, Market({"BTCUSDT": uptrend()}), NOW)
    assert not broker.positions() and "model" in rep.of("watching")[0].detail
    agent.decision_model = ConstantModel("buy", 0.9)
    later = NOW + timedelta(minutes=1)
    rep = agent.tick({"BTCUSDT": snapshot(as_of=later, snapshot_id="s2")}, Market({"BTCUSDT": uptrend()}), later)
    assert rep.of("opened")
    (rec,) = agent.trade_log.open_trades()
    assert [v["name"] for v in rec.votes] == ["news", "technical", "model", "risk"]
    assert rec.context["symbol"] == "BTCUSDT" and "price" in rec.context  # saved for future training


@pytest.mark.skipif(not os.environ.get("TU_SLOW_TESTS"), reason="downloads a tiny model and trains it (set TU_SLOW_TESTS=1)")
def test_tiny_model_trains_end_to_end(tmp_path):
    pytest.importorskip("trl")
    from trading_universe.training.dataset import write_jsonl
    from trading_universe.training.models import HFDecisionModel
    from trading_universe.training.retraining import evaluate
    from trading_universe.training.train import TrainConfig, merge, rl, sft

    df = frame([100 * 1.002**i for i in range(120)])
    entries = pd.Series(True, index=df.index)
    exs = examples_from_history({"X": df}, {"X": entries})[:16]
    p = write_jsonl(exs, tmp_path / "t.jsonl")
    base = "trl-internal-testing/tiny-Qwen2ForCausalLM-2.5"
    m = merge(sft(p, TrainConfig(base_model=base, output_dir=str(tmp_path / "s"), max_steps=1, batch_size=4)), str(tmp_path / "m"))
    m2 = merge(rl(p, m, TrainConfig(base_model=m, output_dir=str(tmp_path / "r"), max_steps=1, batch_size=4)), str(tmp_path / "m2"))
    assert evaluate(HFDecisionModel(m2), exs[:2]).n == 2
