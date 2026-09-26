"""Control room for the trading agent.

Run locally:      streamlit run app/dashboard.py
Run in the cloud: deploy this file on Streamlit Community Cloud (see README).
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from trading_universe.backtest.data import fetch, synthetic_prices  # noqa: E402
from trading_universe.backtest.engine import PROFILES, Setting, build_grid  # noqa: E402
from trading_universe.backtest.optimize import optimize  # noqa: E402
from trading_universe.backtest.plots import CHOSEN_COLOR, CURRENT_COLOR, hidden_year_curves  # noqa: E402
from trading_universe.backtest.signals import long_signals  # noqa: E402
from trading_universe.config import RISK_BUDGET_MAX_INR, RISK_BUDGET_MIN_INR  # noqa: E402

# Reference palette (categorical slots in fixed order) and neutral inks.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
UP, DOWN = "#1baf7a", "#eb6834"
MUTED, GRID = "#6b6a65", "rgba(128,128,128,0.18)"

POPULAR = {
    "crypto": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"],
    "stock": ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "AAPL", "MSFT", "NVDA", "TSLA"],
}
RUNS = ROOT / "runs"

st.set_page_config(page_title="Trading Agent Control Room", page_icon="📈", layout="wide")


# ---------------------------------------------------------------------------- data


@st.cache_data(ttl=3600, show_spinner=False)
def load_prices(market: str, symbols: tuple[str, ...], interval: str, start: str, demo: bool) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    data, errors = {}, {}
    for i, sym in enumerate(symbols):
        try:
            if demo:
                data[sym] = synthetic_prices(6 * 365, seed=i, vol=0.035 if market == "crypto" else 0.015, calendar="24/7" if market == "crypto" else "weekdays")
            else:
                data[sym] = fetch(sym, market, interval, start)
        except Exception as e:  # show the problem next to the symbol instead of crashing the page
            errors[sym] = str(e)
    return data, errors


@st.cache_data(show_spinner=False)
def run_search(market: str, symbols: tuple[str, ...], interval: str, start: str, demo: bool, holdout_days: int, min_trades: int, current: Setting):
    data, _ = load_prices(market, symbols, interval, start, demo)
    profile = PROFILES[market]
    report = optimize(data, build_grid(stop_losses=profile.stop_losses), holdout_days=holdout_days, min_practice_trades=min_trades, current=current, costs=profile.costs)
    curves = hidden_year_curves(report, data, profile.costs)
    return report, curves


def rupees(x: float) -> str:
    return f"{'−' if x < 0 else '+'}₹{abs(x):,.0f}"


def pct(x: float) -> str:
    return f"{x:+.1%}"


def style(fig: go.Figure, height: int = 420, ytitle: str = "") -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0),
        yaxis_title=ytitle,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


# ------------------------------------------------------------------------- sidebar

with st.sidebar:
    st.header("What to look at")
    market_label = st.radio("Market", ["Crypto (Binance)", "Stocks (Yahoo Finance)"], horizontal=False)
    market = "crypto" if market_label.startswith("Crypto") else "stock"
    picked = st.multiselect(
        "Coins" if market == "crypto" else "Stocks",
        POPULAR[market],
        default=POPULAR[market][:4],
        help="Crypto: Binance pairs like BTCUSDT. Stocks: Yahoo tickers — India NSE ends with .NS (RELIANCE.NS), BSE with .BO.",
    )
    extra = st.text_input("Add others (comma separated)", placeholder="e.g. PEPEUSDT" if market == "crypto" else "e.g. TATAMOTORS.NS")
    symbols = tuple(dict.fromkeys([*picked, *[s.strip().upper() for s in extra.split(",") if s.strip()]]))
    intervals = ["1d", "4h", "1h"] if market == "crypto" else ["1d"]
    interval = st.selectbox("Candle size", intervals, help="1d = one candle per day.")
    start = st.date_input("History from", date(2020, 1, 1), min_value=date(2015, 1, 1)).isoformat()
    demo = st.toggle("Use generated prices (offline demo)", value=False, help="Only for trying the app when the data source is unreachable.")

    st.header("Agent settings")
    st.caption("The current rules. The settings search compares its winners against these.")
    risk = st.slider("Risk per trade (₹)", int(RISK_BUDGET_MIN_INR), int(RISK_BUDGET_MAX_INR), 250, step=10, help="Money lost when a stop-loss is hit = 1 R. Fixed at ₹200–300 by the business rules.")
    stop = st.select_slider("Stop-loss", [0.01, 0.015, 0.02, 0.03, 0.05, 0.07, 0.10], value=0.02, format_func=lambda v: f"{v:.1%}")
    trend = st.select_slider("Trend line (days)", [10, 20, 30, 50, 100, 200], value=20)
    breakout = st.select_slider("Breakout window (candles)", [5, 10, 20], value=10)
    triggers = st.multiselect("Entry patterns", ["engulfing", "wick", "breakout"], default=["engulfing", "wick", "breakout"],
                              help="engulfing: a big candle swallows the previous one · wick: hammer-shaped rejection · breakout: close above the recent high")
    if not triggers:
        st.warning("Pick at least one entry pattern.")
        triggers = ["breakout"]
    current = Setting(trend, breakout, tuple(t for t in ("engulfing", "wick", "breakout") if t in triggers), stop)

st.title("📈 Trading Agent Control Room")
if not symbols:
    st.info("Pick at least one coin or stock in the sidebar.")
    st.stop()

with st.spinner(f"Loading prices for {len(symbols)} symbol(s)…"):
    data, errors = load_prices(market, symbols, interval, start, demo)
for sym, err in errors.items():
    st.error(f"{sym}: couldn't load prices — {err}")
if not data:
    st.stop()
if demo:
    st.warning("Showing **generated** prices (demo mode). Results mean nothing for real trading.")

tab_prices, tab_search, tab_trades, tab_memory, tab_status = st.tabs(
    ["📈 Prices", "🧪 Find best settings", "📒 Trade log", "🧠 Memory", "🗺️ Status & next steps"]
)

# -------------------------------------------------------------------------- prices

with tab_prices:
    rows = []
    for sym, df in data.items():
        c = df["close"]
        daily = c.resample("1D").last().dropna()

        def back(days: int) -> float:
            past = daily[daily.index <= daily.index[-1] - pd.Timedelta(days=days)]
            return c.iloc[-1] / past.iloc[-1] - 1 if len(past) else float("nan")

        ma200 = daily.rolling(200).mean().iloc[-1]
        rows.append({
            "Symbol": sym,
            "Last price": c.iloc[-1],
            "1 day": back(1),
            "30 days": back(30),
            "1 year": back(365),
            "Market mood": "—" if pd.isna(ma200) else ("🟢 above 200-day avg" if daily.iloc[-1] > ma200 else "🔴 below 200-day avg"),
            "Candles": len(df),
            "From": df.index[0].date(),
            "To": df.index[-1].date(),
        })
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Last price": st.column_config.NumberColumn(format="%.4g"),
            "1 day": st.column_config.NumberColumn(format="percent"),
            "30 days": st.column_config.NumberColumn(format="percent"),
            "1 year": st.column_config.NumberColumn(format="percent"),
        },
    )
    st.caption("Market mood: above its 200-day average usually means a rising market, below means falling (roadmap step 1).")

    sym = st.selectbox("Chart", list(data), key="chart_symbol")
    df = data[sym]
    window = st.select_slider("Show last", ["3 months", "6 months", "1 year", "2 years", "All"], value="1 year")
    days = {"3 months": 91, "6 months": 182, "1 year": 365, "2 years": 730}.get(window)
    view = df if days is None else df[df.index >= df.index[-1] - pd.Timedelta(days=days)]
    entries, _ = long_signals(df, current.trend_window, current.breakout_window, current.triggers)
    sma = df["close"].rolling(current.trend_window).mean()
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=view.index, open=view["open"], high=view["high"], low=view["low"], close=view["close"], name=sym,
                                 increasing=dict(line=dict(color=UP), fillcolor=UP), decreasing=dict(line=dict(color=DOWN), fillcolor=DOWN)))
    fig.add_trace(go.Scatter(x=view.index, y=sma.loc[view.index], name=f"{current.trend_window}-candle trend line", line=dict(color=SERIES[0], width=2)))
    buys = view.index[entries.loc[view.index]]
    fig.add_trace(go.Scatter(x=buys, y=view.loc[buys, "low"] * 0.985, mode="markers", name="price rules say buy",
                             marker=dict(symbol="triangle-up", size=10, color=SERIES[3], line=dict(color="white", width=1))))
    fig.update_layout(xaxis_rangeslider_visible=False)
    st.plotly_chart(style(fig, 480, "price"), use_container_width=True)
    st.caption("▲ = days when the Technical check (trend + entry pattern) would agree to buy. A real trade also needs the News and Risk checks.")

    if len(data) > 1:
        comp = go.Figure()
        for (s, d), color in zip(data.items(), SERIES):
            idx = d["close"] / d["close"].iloc[0] * 100
            comp.add_trace(go.Scatter(x=idx.index, y=idx.values, name=s, line=dict(color=color, width=2)))
        comp.update_yaxes(type="log")
        st.subheader("Compare (start = 100)")
        st.plotly_chart(style(comp, 360, "start = 100 (log scale)"), use_container_width=True)

# -------------------------------------------------------------------------- search

with tab_search:
    st.markdown(
        "Tests every combination of trend line, breakout window, entry patterns and stop-loss (525 settings). "
        "**The last part of history stays hidden** while searching; the top 5 then take an exam on it. "
        "A setting is used only if it still makes money on the hidden period. 1 R = one stop-loss hit = your risk per trade."
    )
    c1, c2 = st.columns(2)
    holdout = c1.select_slider("Hide the last", [90, 180, 365, 730], value=365, format_func=lambda d: f"{d} days")
    min_trades = c2.select_slider("Ignore settings with fewer practice trades than", [10, 20, 30, 50, 100], value=30)
    if st.button("▶ Run settings search", type="primary"):
        st.session_state["search_args"] = (market, symbols, interval, start, demo, holdout, min_trades, current)
    args = st.session_state.get("search_args")
    if args and args[:5] != (market, symbols, interval, start, demo):
        st.info("The coins or history changed since the last run. Press **Run settings search** again.")
        args = None
    if args:
        try:
            with st.spinner("Testing settings… (about 20–60 seconds)"):
                report, curves = run_search(*args)
        except ValueError as e:
            st.error(f"Couldn't run the search: {e}")
            report = None
    if args and report is not None:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Settings tested", report.settings_tested)
        m2.metric("Profitable in practice", report.settings_eligible)
        m3.metric("Passed hidden exam", sum(w.passed for w in report.winners))
        m4.metric("Decision", "Switch" if report.chosen else "Keep", help="Switch = a new setting passed the exam. Keep = stay with the current settings.")
        st.caption(f"Practice: {report.practice_period[0]:%d %b %Y} → {report.practice_period[1]:%d %b %Y} · "
                   f"Hidden: {report.exam_period[0]:%d %b %Y} → {report.exam_period[1]:%d %b %Y}")

        table = []
        for i, r in enumerate([*report.winners, *([report.current] if report.current else [])]):
            s_ = r.setting
            table.append({
                # Most important first, so it stays visible on narrow screens.
                "Rank": "current" if r is report.current else f"#{i + 1}",
                "Exam": "✅ PASS" if r.passed else "❌ FAIL",
                "Hidden profit": f"{r.exam.total_r:+.0f} R ({rupees(r.exam.total_r * risk)})",
                "Practice profit": f"{r.practice.total_r:+.0f} R ({rupees(r.practice.total_r * risk)})",
                "Setting": f"trend {s_.trend_window} · breakout {s_.breakout_window} · {'+'.join(s_.triggers)} · stop {s_.stop_loss_pct:.1%}",
                "Hidden period": f"{r.exam.trades} trades, {r.exam.win_rate:.0%} won",
                "Practice": f"{r.practice.trades} trades, {r.practice.win_rate:.0%} won",
                "Why": r.reason,
            })
        st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)

        if curves:
            fig = go.Figure()
            first = min(d.index.min() for d in data.values())
            last = max(d.index.max() for d in data.values())
            fig.add_vrect(x0=report.cutoff, x1=last, fillcolor="rgba(128,128,128,0.15)", line_width=0,
                          annotation_text="hidden period", annotation_position="top left")
            for name, color, r in curves:
                curve = pd.concat([pd.Series([0.0], index=[first]), r.cumsum()])
                fig.add_trace(go.Scatter(x=curve.index, y=curve.values, name=name, line=dict(color=color, width=2, shape="hv"),
                                         customdata=curve.values * risk, hovertemplate="%{y:+.1f} R (₹%{customdata:,.0f})"))
            fig.add_hline(y=0, line_color=MUTED, line_width=1)
            st.plotly_chart(style(fig, 420, "running profit (R)"), use_container_width=True)

        if report.chosen:
            s = report.chosen
            st.success(f"Winner: trend {s.trend_window}, breakout {s.breakout_window}, patterns {' + '.join(s.triggers)}, stop {s.stop_loss_pct:.1%}. "
                       "Set these in the sidebar to make them the current rules.")
            st.download_button("Download winning setting (JSON)", json.dumps(asdict(s), indent=2), "best_setting.json", "application/json")
        else:
            st.warning("No setting held up on the hidden period, so the current settings stay.")

# ---------------------------------------------------------------------- trade log

with tab_trades:
    log_path = RUNS / "trades.jsonl"
    if log_path.exists():
        from trading_universe.trade_log import TradeLog

        recs = TradeLog(log_path).all()
        df_log = pd.DataFrame([{
            "Opened": r.opened_at, "Symbol": r.symbol, "Side": r.action, "Qty": r.quantity, "Entry": r.entry_price,
            "Stop": r.stop_price, "Risk ₹": r.risk_amount, "Exit": r.exit_price, "Why closed": r.exit_reason, "P&L ₹": r.pnl,
        } for r in recs])
        closed = df_log["P&L ₹"].dropna()
        a, b, c = st.columns(3)
        a.metric("Trades", len(df_log))
        b.metric("Open now", int(df_log["Exit"].isna().sum()))
        c.metric("Total P&L", rupees(closed.sum()) if len(closed) else "—")
        st.dataframe(df_log, hide_index=True, use_container_width=True)
    else:
        st.info("No trades yet. Paper trading (fake money on the Binance testnet) hasn't started, so there's nothing to show. "
                f"Trades will appear here from `{log_path.relative_to(ROOT)}`.")

# ------------------------------------------------------------------------- memory

with tab_memory:
    mem_path = RUNS / "memory.json"
    if mem_path.exists():
        raw = json.loads(mem_path.read_text())
        recs = raw.get("records", [])
        st.metric("Saved lessons and notes", len(recs))
        st.dataframe(pd.DataFrame([{
            "Shelf": "team lead lesson" if r["kind"] == "pattern" else "coin note",
            "Owner": r["owner_id"], "Text": r["text"], "Learned on": r["valid_from"][:10],
            "Evidence": len(r["evidence"]), "Wins": sum(o[1] for o in r["outcomes"]),
            "Losses": sum(not o[1] for o in r["outcomes"]), "Retired": (r["retired_at"] or "")[:10],
        } for r in recs]), hide_index=True, use_container_width=True)
        if raw.get("dormant"):
            st.caption("Sleeping shelves: " + ", ".join(raw["dormant"]))
    else:
        st.info("The shared memory is empty. It fills up once the research agents start writing lessons. "
                f"It will be read from `{mem_path.relative_to(ROOT)}`.")

# ------------------------------------------------------------------------- status

with tab_status:
    roadmap = ROOT / "ROADMAP.md"
    st.markdown(roadmap.read_text() if roadmap.exists() else "ROADMAP.md not found.")
