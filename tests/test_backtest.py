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


def test_load_csv_accepts_yahoo_style_export(tmp_path):
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
