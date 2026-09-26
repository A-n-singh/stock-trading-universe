"""Charts for the notebook: running profit (in R) over time, with the hidden year shaded."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from .engine import Costs, Setting, trade_r_multiples
from .optimize import Report

# Categorical slots 1 and 2 of the reference palette (validated for colour-blind separation).
CHOSEN_COLOR = "#2a78d6"  # blue
CURRENT_COLOR = "#eb6834"  # orange
INK, MUTED, GRID = "#1f1f1e", "#6b6a65", "#e4e3de"


def _rupees(x: float) -> str:
    return f"{'−' if x < 0 else '+'}₹{abs(x):,.0f}"


def _label_ends(ax, ends: list[tuple[pd.Timestamp, float, str]], min_gap_pt: float = 12) -> None:
    """Direct labels at line ends, pushed apart vertically so they never overlap."""
    import matplotlib.dates as mdates

    ax.autoscale_view()
    to_px = ax.transData.transform
    pts = sorted(((to_px((mdates.date2num(pd.Timestamp(x)), y))[1], x, y, text) for x, y, text in ends), key=lambda t: t[0])
    pt_to_px = ax.figure.dpi / 72
    placed: list[float] = []
    for py, x, y, text in pts:
        target = py if not placed else max(py, placed[-1] + min_gap_pt * pt_to_px)
        placed.append(target)
        ax.annotate(text, (x, y), xytext=(6, (target - py) / pt_to_px), textcoords="offset points", va="center", color=INK, fontsize=9)


def hidden_year_curves(report: Report, data: Mapping[str, pd.DataFrame], costs: Costs = Costs()) -> list[tuple[str, str, pd.Series]]:
    """(label, colour, per-trade R series) for the chosen/best setting and the current one.

    Exactly the trades the report counts: practice trades from the practice years only, exam
    trades = those *entered* in the hidden year. A trade entered before the cutoff that closes
    after it belongs to neither, just as in the report.
    """
    lines: list[tuple[str, Setting, str]] = []
    best = report.chosen or (report.winners[0].setting if report.winners else None)
    if best is not None:
        lines.append(("chosen" if report.chosen else "best practice setting (failed exam)", best, CHOSEN_COLOR))
    if report.current is not None:
        lines.append(("current setting", report.current.setting, CURRENT_COLOR))
    if not lines:
        return []
    settings = [s for _, s, _ in lines]
    practice = {sym: df[df.index <= report.cutoff] for sym, df in data.items()}
    series = [
        pd.concat([p, e])
        for p, e in zip(
            trade_r_multiples(practice, settings, costs, market_ok=report.market_ok),
            trade_r_multiples(data, settings, costs, count_entries_after=report.cutoff, market_ok=report.market_ok),
        )
    ]
    return [(name, color, r) for (name, _, color), r in zip(lines, series)]


def plot_hidden_year(report: Report, data: Mapping[str, pd.DataFrame], costs: Costs = Costs(), risk_per_trade: float = 250.0, ax=None):
    """Running total of R for the chosen setting vs the current one; the hidden year is shaded."""
    import matplotlib.pyplot as plt

    curves = hidden_year_curves(report, data, costs)
    if not curves:
        raise ValueError("nothing to plot: no settings had enough trades")
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4.5))
    start = min(df.index.min() for df in data.values())
    end = max(df.index.max() for df in data.values())
    ax.axvspan(report.cutoff, end, color=GRID, alpha=0.6, lw=0)
    ax.axhline(0, color=MUTED, lw=0.8)
    ends = []
    for name, color, r in curves:
        curve = pd.concat([pd.Series([0.0], index=[start]), r.cumsum()])
        ax.step(curve.index, curve.values, where="post", color=color, lw=2, label=name)
        total = curve.iloc[-1]
        ends.append((curve.index[-1], total, f"{total:+.0f} R ({_rupees(total * risk_per_trade)})"))
    ax.text(report.cutoff, 1.0, "  hidden year", transform=ax.get_xaxis_transform(), va="top", color=MUTED, fontsize=9)
    ax.set_ylabel("running profit (R)", color=MUTED)
    ax.set_title("Practice years vs hidden year", color=INK, loc="left")
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED)
    ax.legend(frameon=False, loc="best", labelcolor=INK)
    ax.margins(x=0.12)
    _label_ends(ax, ends)
    return ax


def plot_prices(data: Mapping[str, pd.DataFrame], cutoff: pd.Timestamp | None = None, ax=None):
    """Each coin's price indexed to 100 at the start (one shared axis, so coins are comparable)."""
    import matplotlib.pyplot as plt

    palette = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4))
    ends = []
    for (sym, df), color in zip(data.items(), palette):
        idx = df["close"] / df["close"].iloc[0] * 100
        ax.plot(idx.index, idx.values, color=color, lw=2, label=sym)
        ends.append((idx.index[-1], idx.iloc[-1], sym))
    if cutoff is not None:
        ax.axvspan(cutoff, max(df.index.max() for df in data.values()), color=GRID, alpha=0.6, lw=0)
    ax.set_yscale("log")
    ax.set_ylabel("price, start = 100 (log scale)", color=MUTED)
    ax.set_title("Coin prices", color=INK, loc="left")
    ax.grid(axis="y", color=GRID, lw=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=MUTED)
    ax.legend(frameon=False, loc="upper left", labelcolor=INK)
    ax.margins(x=0.1)
    _label_ends(ax, ends)
    return ax
