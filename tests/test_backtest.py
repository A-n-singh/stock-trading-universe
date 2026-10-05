from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("vectorbt")

from trading_universe.backtest import (  # noqa: E402
    HiddenYear,
    Setting,
    apply_setting,
    optimize,
    run_grid,
    setting_from_config,
    split_hidden_year,
)
from trading_universe.backtest.data import load_csv, synthetic_prices  # noqa: E402
from trading_universe.backtest.engine import ALL_TRIGGERS, Costs, build_grid  # noqa: E402
from trading_universe.backtest.signals import long_signals  # noqa: E402
from trading_universe.config import AgentConfig  # noqa: E402
from trading_universe.models import Action, Candle  # noqa: E402
from trading_universe.trading_agent.technical import technical_vote  # noqa: E402

SMALL_GRID = build_grid(trend_windows=(10, 30), breakout_windows=(5, 10), stop_losses=(0.02, 0.04))


def candles(df) -> list[Candle]:
    return [Candle(ts, r.open, r.high, r.low, r.close, r.volume) for ts, r in df.iterrows()]


@pytest.mark.parametrize("trend,breakout", [(10, 5), (20, 10)])
def test_vector_signals_match_the_live_technical_gate(trend, breakout):
    """The backtest must test the same rule the agent trades, bar by bar."""
    df = synthetic_prices(160, seed=3, vol=0.03)
    cs = candles(df)
    for n in (1, 2, 3):
        for trig in itertools.combinations(ALL_TRIGGERS, n):
            entries, _ = long_signals(df, trend, breakout, trig)
            live = [technical_vote(cs[: i + 1], Action.BUY, trend, breakout, trig).approve for i in range(len(cs))]
            assert entries.tolist() == live, trig


def test_hidden_year_is_removed_from_practice_data():
    data = {"A": synthetic_prices(5 * 365)}
    practice, cutoff = split_hidden_year(data, 365)
    assert practice["A"].index.max() <= cutoff
    assert (data["A"].index.max() - cutoff).days == 365


def test_hidden_year_opens_once_and_only_for_a_few_settings():
    data = {"A": synthetic_prices(3 * 365)}
    _, cutoff = split_hidden_year(data)
    vault = HiddenYear(data, cutoff, Costs(), max_exam_settings=3)
    with pytest.raises(ValueError):
        vault.exam(SMALL_GRID[:4])  # can't be used to search
    vault.exam(SMALL_GRID[:2])
    with pytest.raises(RuntimeError):
        vault.exam(SMALL_GRID[:1])  # can't be re-used


def test_changing_the_hidden_year_does_not_change_the_winners():
    """Proof that the search never looked at the hidden year."""
    data = {f"S{i}": synthetic_prices(5 * 365, seed=i, drift=0.003, vol=0.01) for i in range(3)}
    _, cutoff = split_hidden_year(data)
    scrambled = {}
    for sym, df in data.items():
        df = df.copy()
        hidden = df.index > cutoff
        df.loc[hidden, ["open", "high", "low", "close"]] *= 0.5  # wildly different future
        scrambled[sym] = df
    a = optimize(data, SMALL_GRID, min_practice_trades=5)
    b = optimize(scrambled, SMALL_GRID, min_practice_trades=5)
    assert a.winners, "test needs at least one winner to be meaningful"
    assert [w.setting for w in a.winners] == [w.setting for w in b.winners]
    assert [w.practice for w in a.winners] == [w.practice for w in b.winners]
    assert [w.exam for w in a.winners] != [w.exam for w in b.winners]


def test_real_edge_survives_the_exam():
    # A steady uptrend in every year: trend-following genuinely works, before and after the cutoff.
    data = {f"UP{i}": synthetic_prices(5 * 365, seed=i, drift=0.003, vol=0.01) for i in range(3)}
    report = optimize(data, SMALL_GRID, min_practice_trades=5, current=setting_from_config(AgentConfig()))
    assert report.chosen is not None
    chosen = next(w for w in report.winners if w.setting == report.chosen)
    assert chosen.passed and chosen.exam.total_r > 0
    assert "Hidden year" in report.to_text()


def test_stop_loss_trade_scores_about_minus_one_r():
    idx = pd.bdate_range("2021-01-01", periods=40)
    rows = [(100 + i, 100.6 + i, 99.8 + i, 100.5 + i) for i in range(30)]  # steady rise -> breakouts
    entry = rows[-1][3]
    rows += [(entry - 0.2, entry, entry * 0.9, entry * 0.92)]  # drops through a 4% stop
    rows += [(entry * 0.92, entry * 0.93, entry * 0.91, entry * 0.92)] * 9
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1.0
    s = Setting(10, 5, ("breakout",), 0.04)
    only_last_entry = pd.Timestamp(idx[28])
    [score] = run_grid({"X": df}, [s], Costs(0, 0), count_entries_after=only_last_entry)
    assert score.trades == 1
    assert score.total_r == pytest.approx(-1.0, abs=0.05)


def test_apply_setting_updates_agent_config_but_not_risk_budget():
    cfg = AgentConfig()
    new = apply_setting(cfg, Setting(50, 20, ("breakout",), 0.03))
    assert new.technical.trend_window == 50 and new.technical.triggers == frozenset({"breakout"})
    assert new.risk.stop_loss_pct == 0.03 and new.risk.risk_per_trade == cfg.risk.risk_per_trade
    assert setting_from_config(new) == Setting(50, 20, ("breakout",), 0.03)


def test_load_csv_accepts_an_exported_candle_file(tmp_path):
    p = tmp_path / "infy.csv"
    p.write_text("Date,Open,High,Low,Close,Adj Close,Volume\n2024-01-02,10,11,9,10.5,10.4,100\n2024-01-01,9,10,8,9.5,9.4,90\n")
    df = load_csv(p)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.is_monotonic_increasing and df["close"].iloc[-1] == 10.5


# ---- crypto ------------------------------------------------------------------


def test_crypto_prices_include_weekends():
    df = synthetic_prices(14)
    assert len(df) == 14 and (df.index[-1] - df.index[0]).days == 13


def test_load_raw_binance_bulk_file_ms_and_us(tmp_path):
    ms = tmp_path / "BTCUSDT-1d-2024-01.csv"
    ms.write_text("1704067200000,42283.58,44184.1,42180.77,44179.55,27174.3,1704153599999,0,0,0,0,0\n")
    us = tmp_path / "BTCUSDT-1d-2025-01.csv"
    us.write_text("1735689600000000,93576.0,95151.15,92888.0,94591.79,10373.3,1735775999999999,0,0,0,0,0\n")
    assert load_csv(ms).index[0] == pd.Timestamp("2024-01-01")
    assert load_csv(us).index[0] == pd.Timestamp("2025-01-01")
    assert load_csv(us)["close"].iloc[0] == 94591.79


def test_fetch_binance_pages_through_history(monkeypatch):
    import json as _json

    from trading_universe.backtest import data as data_mod

    day = 86_400_000
    start = int(pd.Timestamp("2024-01-01").timestamp() * 1000)
    calls = []

    def fake_get(url, timeout=30):
        calls.append(url)
        q = dict(p.split("=") for p in url.split("?")[1].split("&"))
        t0 = -(-int(q["startTime"]) // day) * day  # like Binance: next candle open at or after startTime
        n = max(0, min(1000, (start + 1500 * day - t0) // day))
        rows = [[t0 + i * day, "1", "2", "0.5", "1.5", "10", 0, 0, 0, 0, 0, 0] for i in range(n)]
        return _json.dumps(rows).encode()

    monkeypatch.setattr(data_mod, "_get", fake_get)
    monkeypatch.setattr(data_mod.time, "sleep", lambda s: None)
    df = data_mod.fetch_binance("btcusdt", "1d", "2024-01-01", "2030-01-01")
    assert len(df) == 1500 and "symbol=BTCUSDT" in calls[0] and len(calls) == 2


def _zip(name: str, text: str) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


def test_falls_back_to_bulk_archive_when_api_is_region_blocked(monkeypatch):
    """Google Colab runs in the US, where Binance's API answers HTTP 451."""
    import urllib.error

    from trading_universe.backtest import data as data_mod

    served = []

    def fake_get(url, timeout=30):
        if "/api/v3/" in url:
            raise urllib.error.HTTPError(url, 451, "Unavailable For Legal Reasons", {}, None)
        served.append(url)
        if url.endswith("BTCUSDT-1d-2024-01.zip"):  # header row + microsecond timestamps, like newer files
            return _zip("a.csv", "open_time,open,high,low,close,volume\n1704067200000000,1,2,0.5,1.5,10,0,0,0,0,0,0\n")
        if url.endswith("BTCUSDT-1d-2024-02.zip"):
            return _zip("b.csv", "1706745600000,2,3,1,2.5,10,0,0,0,0,0,0\n")
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(data_mod, "_get", fake_get)
    df = data_mod.fetch_binance("BTCUSDT", "1d", "2024-01-01", "2024-03-05")
    assert list(df.index) == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01")]
    assert df["close"].tolist() == [1.5, 2.5]
    assert any("/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01.zip" in u for u in served)
    assert any("/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-03-05.zip" in u for u in served)


def test_works_on_4h_crypto_candles():
    df = synthetic_prices(600, seed=1)
    df.index = pd.date_range("2024-01-01", periods=600, freq="4h")
    [score] = run_grid({"BTC": df}, [Setting(20, 10, ALL_TRIGGERS, 0.05)])
    assert score.trades > 0


def test_hidden_year_chart_shows_the_same_numbers_as_the_report():
    import matplotlib

    matplotlib.use("Agg")
    from trading_universe.backtest.plots import plot_hidden_year, plot_prices

    data = {f"UP{i}": synthetic_prices(5 * 365, seed=i, drift=0.003, vol=0.01) for i in range(2)}
    report = optimize(data, SMALL_GRID, min_practice_trades=5, current=setting_from_config(AgentConfig()))
    ax = plot_hidden_year(report, data)
    for line, result in zip(ax.get_lines()[1:], [w for w in report.winners if w.setting == report.chosen] + [report.current]):
        assert line.get_ydata()[-1] == pytest.approx(result.practice.total_r + result.exam.total_r)
    plot_prices(data, report.cutoff)
    matplotlib.pyplot.close("all")


def test_market_filter_blocks_buys_while_the_leader_is_below_its_average():
    from trading_universe.backtest.engine import market_mood

    up = synthetic_prices(400, seed=1, drift=0.004, vol=0.01)
    down = up.copy()
    down[["open", "high", "low", "close"]] = up[["open", "high", "low", "close"]].iloc[::-1].to_numpy()  # same path, falling
    s = Setting(20, 5, ALL_TRIGGERS, 0.05)
    [free] = run_grid({"X": up}, [s])
    [blocked] = run_grid({"X": up}, [s], market_ok=market_mood(down, 50))
    [allowed] = run_grid({"X": up}, [s], market_ok=market_mood(up, 50))
    assert free.trades > 0 and blocked.trades < free.trades // 4
    assert allowed.trades > blocked.trades
    mood = market_mood(up, 50)
    assert not mood.iloc[:49].any()  # no verdict before 50 days of history: no buying


def test_fair_exam_passes_small_losses_in_a_falling_market():
    from trading_universe.backtest.engine import Score
    from trading_universe.backtest.optimize import hold_r, judge

    practice = Score(100, 50.0, 0.5, 0.5, 5.0)
    small_loss = Score(15, -4.6, -0.3, 0.4, 6.0)
    # Coins fell 20% and 30%; with a 2% stop, holding the same-sized positions lost 10 R + 15 R.
    hold = hold_r({"A": -0.20, "B": -0.30}, 0.02)
    assert hold == pytest.approx(-25.0)
    ok, why, kind = judge(practice, small_loss, 5, 0.5, hold, max_loss_vs_hold=0.25)
    assert ok and kind == "beat_hold" and "25.0 R" in why
    # Same loss, but the old (profit-only) exam fails it.
    assert judge(practice, small_loss, 5, 0.5, hold, max_loss_vs_hold=None)[0] is False
    # Losing more than a quarter of what holding lost still fails.
    assert judge(practice, Score(15, -10.0, -0.7, 0.3, 12.0), 5, 0.5, hold, 0.25)[0] is False
    # When the coins went up, a loss is a loss.
    assert judge(practice, small_loss, 5, 0.5, 30.0, 0.25)[0] is False
    # Sitting in cash with too few trades never passes.
    assert judge(practice, Score(2, -0.5, -0.25, 0.5, 1.0), 5, 0.5, hold, 0.25)[0] is False


def test_report_includes_buy_and_hold_of_each_coin():
    data = {f"C{i}": synthetic_prices(3 * 365, seed=i, vol=0.03) for i in range(2)}
    rep = optimize(data, build_grid(trend_windows=(20,), breakout_windows=(10,), stop_losses=(0.03,)), holdout_days=180,
                   min_practice_trades=1, current=setting_from_config(AgentConfig()))
    assert set(rep.hold_returns) == {"C0", "C1"}
    for sym, df in data.items():
        cut = df[df.index <= rep.cutoff]["close"].iloc[-1]
        assert rep.hold_returns[sym] == pytest.approx(df["close"].iloc[-1] / cut - 1 - 2 * 0.0015)
    assert rep.current.hold_r == pytest.approx(sum(rep.hold_returns.values()) / rep.current.setting.stop_loss_pct)
    assert "holding the coins instead" in rep.to_text()


def test_losing_less_never_replaces_a_current_setting_that_made_money(monkeypatch):
    import importlib

    from trading_universe.backtest.engine import Score

    opt = importlib.import_module("trading_universe.backtest.optimize")  # the module, not the function
    data = {f"C{i}": synthetic_prices(3 * 365, seed=i, vol=0.03) for i in range(2)}
    grid = build_grid(trend_windows=(20,), breakout_windows=(10,), stop_losses=(0.03,), trigger_sets=[("breakout",)])
    current = Setting(30, 5, ("wick",), 0.02)
    practice = Score(100, 50.0, 0.5, 0.5, 5.0)

    def fake_run_grid(d, settings, costs, count_entries_after=None, market_ok=None, shorts=False):
        if count_entries_after is None:
            return [practice for _ in settings]
        return [Score(10, 5.0, 0.5, 0.5, 1.0) if s == current else Score(10, -2.0, -0.2, 0.3, 3.0) for s in settings]

    monkeypatch.setattr(opt, "run_grid", fake_run_grid)
    monkeypatch.setattr(opt, "hold_returns", lambda *a, **k: {"C0": -0.3, "C1": -0.3})
    rep = opt.optimize(data, grid, holdout_days=180, min_practice_trades=1, current=current)
    assert rep.winners[0].pass_kind == "beat_hold" and rep.current.pass_kind == "profit"
    assert rep.chosen is None  # keep the current setting
    # Also when the current setting made money but failed another check (e.g. kept too little edge).
    rep = opt.optimize(data, grid, holdout_days=180, min_practice_trades=1, current=current, min_edge_kept=2.0)
    assert not rep.current.passed and rep.current.exam.total_r > 0 and rep.chosen is None

    rep = opt.optimize(data, grid, holdout_days=180, min_practice_trades=1)  # no current setting to protect
    assert rep.chosen == grid[0]


@pytest.mark.parametrize("trend,breakout", [(10, 5), (20, 10)])
def test_short_signals_match_the_live_technical_gate(trend, breakout):
    from trading_universe.backtest.signals import short_signals

    df = synthetic_prices(160, seed=5, vol=0.03)
    cs = candles(df)
    for n in (1, 2, 3):
        for trig in itertools.combinations(ALL_TRIGGERS, n):
            entries, _ = short_signals(df, trend, breakout, trig)
            live = [technical_vote(cs[: i + 1], Action.SELL, trend, breakout, trig).approve for i in range(len(cs))]
            assert entries.tolist() == live, trig


def _falling_then(rows_after, n=30):
    idx = pd.date_range("2021-01-01", periods=n + len(rows_after), freq="D")
    rows = [(200 - i, 200.2 - i, 199.4 - i, 199.5 - i) for i in range(n)] + rows_after  # steady fall -> breakdowns
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1.0
    return df, idx


def test_short_trades_score_in_r_with_stop_and_funding():
    from trading_universe.backtest.engine import trade_r_multiples

    s = Setting(10, 5, ("breakout",), 0.04)
    entry = 199.5 - 29
    # Price jumps through the 4% stop above the entry: about −1 R.
    df, idx = _falling_then([(entry + 0.2, entry * 1.10, entry, entry * 1.08)] + [(entry * 1.08,) * 4] * 9)
    all_down = pd.Series(False, index=idx)  # market filter says: falling every day
    [r] = trade_r_multiples({"X": df}, [s], Costs(0, 0, 0), count_entries_after=idx[28], market_ok=all_down, shorts=True)
    assert len(r) == 1 and r.iloc[0] == pytest.approx(-1.0, abs=0.05)
    # Keeps falling, then recovers above the average: a profitable short, minus funding for the days held.
    after = [(entry - 1 - i, entry - 0.8 - i, entry - 1.6 - i, entry - 1.5 - i) for i in range(10)] + [(entry - 5.5,) * 4] * 4  # bounces back above its average: exit
    df, idx = _falling_then(after)
    ok = pd.Series(False, index=idx)
    no_fund = trade_r_multiples({"X": df}, [s], Costs(0, 0, 0), count_entries_after=idx[28], market_ok=ok, shorts=True)[0]
    fund = trade_r_multiples({"X": df}, [s], Costs(0, 0, 0.001), count_entries_after=idx[28], market_ok=ok, shorts=True)[0]
    assert len(no_fund) == 1 and no_fund.iloc[0] == pytest.approx(5.5 / entry / 0.04)  # sold at entry, bought back 5.5 lower
    assert fund.iloc[0] < no_fund.iloc[0]
    # A rising market (filter True every day) allows no shorts, and shorts need the filter at all.
    up = trade_r_multiples({"X": df}, [s], Costs(0, 0, 0), market_ok=pd.Series(True, index=idx), shorts=True)[0]
    longs_only = trade_r_multiples({"X": df}, [s], Costs(0, 0, 0), market_ok=pd.Series(True, index=idx))[0]
    assert up.tolist() == longs_only.tolist()
    with pytest.raises(ValueError):
        trade_r_multiples({"X": df}, [s], shorts=True)
