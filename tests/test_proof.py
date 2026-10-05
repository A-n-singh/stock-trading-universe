"""Proving it makes money: costs, one-candle delay, simple-strategy comparisons, gates and the experiment log."""

from __future__ import annotations

import json

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

from trading_universe.experiments import Registry  # noqa: E402
from trading_universe.proof import (  # noqa: E402
    CostModel, ProofConfig, data_check, regimes, run, simulate, universe_mask,
)

NO_COST = CostModel(0, 0, 0, 0)


def frame(closes, start="2020-01-01", spread=0.01) -> pd.DataFrame:
    c = pd.Series(closes, index=pd.date_range(start, periods=len(closes), freq="D"), dtype=float)
    o = c.shift(1).fillna(c.iloc[0])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * (1 + spread), "low": np.minimum(o, c) * (1 - spread),
                         "close": c, "volume": 1000.0})


def flags(df, days):
    s = pd.Series(False, index=df.index)
    s.iloc[days] = True
    return s


def test_signal_is_filled_at_the_next_open_and_pays_costs():
    df = frame([100, 100, 110, 120, 130, 130])
    trend = pd.Series("flat", index=df.index)
    (t,) = simulate("X", df, {1: flags(df, [1])}, {1: flags(df, [3])}, None, 0.02, NO_COST, trend)
    # Decided on day 1's close, bought at day 2's open (= day 1's close here); sold at day 4's open.
    assert (t.entry_at[:10], t.entry, t.exit_at[:10], t.exit, t.reason) == ("2020-01-03", 100, "2020-01-05", 120, "rule")
    assert t.ret == pytest.approx(0.2, rel=1e-6) and t.r == pytest.approx(t.ret / 0.02)
    (paid,) = simulate("X", df, {1: flags(df, [1])}, {1: flags(df, [3])}, None, 0.02, CostModel(0.001, 0.0002, 0.0005, 0), trend)
    assert paid.ret < t.ret - 0.002  # two fees + spread + slippage


def test_stop_loss_gap_fills_at_the_open_and_shorts_pay_funding():
    df = frame([100, 100, 100, 80, 80])
    trend = pd.Series("flat", index=df.index)
    (t,) = simulate("X", df, {1: flags(df, [1])}, {1: flags(df, [])}, 0.05, 0.05, NO_COST, trend)
    assert t.reason == "stop_loss" and t.exit == pytest.approx(100 * 0.95)  # day 3 opens at 100, falls through 95
    gap = frame([100, 100, 100, 100, 80])
    gap.loc[gap.index[4], "open"] = 70  # opened far below the stop
    (g,) = simulate("X", gap, {1: flags(gap, [1])}, {1: flags(gap, [])}, 0.05, 0.05, NO_COST, trend)
    assert g.exit == 70 and g.r < -5  # a gap can cost more than 1 R

    flat = frame([100] * 12, spread=0.0)
    (s,) = simulate("X", flat, {-1: flags(flat, [0])}, {-1: flags(flat, [10])}, None, 0.02, CostModel(0, 0, 0, 0.001), trend)
    assert s.side == -1 and s.ret == pytest.approx(-0.001 * 10)  # 10 days of funding


def test_data_check_finds_broken_rows():
    good = {"BTCUSDT": frame(list(range(100, 400)))}
    assert data_check(good)["passed"]
    bad = frame(list(range(100, 400)))
    bad = bad.drop(bad.index[50:80])  # 30 missing days
    bad.iloc[100:130, bad.columns.get_loc("high")] = 1  # impossible candles
    rep = data_check({"BTCUSDT": bad})
    assert not rep["passed"] and rep["defects"] > 3 and rep["examples"]


def test_market_types_and_monthly_coin_list_use_only_the_past():
    up = frame([100 * 1.01 ** i for i in range(300)])
    r = regimes(up)
    assert r.iloc[100] == "unknown" and r.iloc[-1] == "rising"
    big = frame([100] * 300)
    small = frame([100] * 300)
    small["volume"] = 1.0
    small.loc[small.index[250]:, "volume"] = 10_000.0  # becomes the most traded late on
    mask = universe_mask({"A": big, "B": small}, size=1)
    assert mask["A"].loc["2020-08-01"] and not mask["B"].loc["2020-08-01"]
    assert mask["B"].iloc[-1] and not mask["A"].iloc[-1]
    assert not mask["A"].iloc[:199].any()  # not before enough history


def test_full_check_reports_gates_and_logs_the_experiment(tmp_path):
    rng = np.random.default_rng(1)
    frames = {s: frame(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.03, 900)))) for s in ("BTCUSDT", "SOLUSDT")}
    rep = run(frames, ProofConfig(coins=tuple(frames), exam_days=200), universe=frames)
    assert set(rep["strategies"]) >= {"ours", "hold", "momentum", "moving_average", "no_mood_filter", "no_shorts",
                                      "ours_double_costs", "ours_universe"}
    assert rep["strategies"]["ours_double_costs"]["practice"]["total_r"] < rep["strategies"]["ours"]["practice"]["total_r"]
    assert set(rep["gates"]) == {"data_check", "edge_check", "robustness"}
    assert rep["gates"]["data_check"]["passed"]
    assert any("beats just holding" in c for c in rep["gates"]["edge_check"]["checks"])
    assert "full_system" in rep["not_testable"] and rep["gemini"] is False
    assert all(t["signal_at"] > rep["period"]["exam_start"] for t in rep["exam_trades"])

    reg = Registry(tmp_path / "experiments.jsonl")
    a = reg.record("edge_check", rep["period"], rep["coins"], {}, rep["rules"], {"ok": True})
    b = reg.record("edge_check", rep["period"], rep["coins"], {}, rep["rules"], {"ok": True})
    assert a["id"] != b["id"] and b["exam_views_before"] == 1 and len(reg.all()) == 2
    assert json.loads((tmp_path / "experiments.jsonl").read_text().splitlines()[0])["code_version"]
