"""Find better price-rule settings without fooling ourselves.

1. Hide the last year of prices (the "exam paper").
2. Test every setting on the earlier years only and keep the top few.
3. Open the hidden year once, test only those few winners on it.
4. Adopt a setting only if it still makes money on the hidden year, or (fairer exam, roadmap step 3)
   if the coins themselves fell and the setting lost much less than simply holding them.
   Otherwise keep the old one.

The hidden year can never be used to *search*: it accepts at most `max_exam_settings`
settings and can be opened only once per run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

import pandas as pd

from ..config import AgentConfig, TechnicalConfig
from .engine import ALL_TRIGGERS, Costs, Score, Setting, build_grid, market_mood, run_grid


def split_hidden_year(data: Mapping[str, pd.DataFrame], holdout_days: int = 365) -> tuple[dict[str, pd.DataFrame], pd.Timestamp]:
    """Return (practice data with the last `holdout_days` removed, cutoff date)."""
    last = max(df.index.max() for df in data.values())
    cutoff = last - pd.Timedelta(days=holdout_days)
    practice = {sym: df[df.index <= cutoff] for sym, df in data.items()}
    if any(len(df) == 0 for df in practice.values()):
        raise ValueError("some symbol has no data before the hidden period")
    return practice, cutoff


class HiddenYear:
    """The exam paper: sealed until the winners are chosen, then opened once for a handful of settings."""

    def __init__(self, data: Mapping[str, pd.DataFrame], cutoff: pd.Timestamp, costs: Costs, max_exam_settings: int = 10,
                 market_ok: pd.Series | None = None, shorts: bool = False) -> None:
        self._data, self.cutoff, self._costs, self._market_ok, self._shorts = data, cutoff, costs, market_ok, shorts
        self.max_exam_settings = max_exam_settings
        self.opened = False

    def exam(self, settings: Sequence[Setting]) -> list[Score]:
        if self.opened:
            raise RuntimeError("the hidden year was already used; re-using it turns the exam into practice")
        if len(settings) > self.max_exam_settings:
            raise ValueError(f"at most {self.max_exam_settings} settings may sit the exam, got {len(settings)}")
        self.opened = True
        # Earlier prices warm up the averages; only trades entered after the cutoff count.
        return run_grid(self._data, settings, self._costs, count_entries_after=self.cutoff, market_ok=self._market_ok,
                        shorts=self._shorts)


def hold_returns(data: Mapping[str, pd.DataFrame], cutoff: pd.Timestamp, costs: Costs = Costs()) -> dict[str, float]:
    """What simply buying each coin at the cutoff and holding to the end returned (after one buy + one sell)."""
    out = {}
    for sym, df in data.items():
        before, after = df[df.index <= cutoff], df[df.index > cutoff]
        if len(before) and len(after):
            out[sym] = float(after["close"].iloc[-1] / before["close"].iloc[-1] - 1) - 2 * (costs.fees + costs.slippage)
    return out


def hold_r(returns: Mapping[str, float], stop_loss_pct: float) -> float:
    """Buy-and-hold in the same units as the agent: one position per coin, sized like the agent sizes a trade
    (1 R lost at the stop-loss, so the position is 1/stop R). A 20% fall with a 2% stop = −10 R per coin."""
    return sum(r / stop_loss_pct for r in returns.values())


@dataclass(frozen=True)
class Result:
    setting: Setting
    practice: Score
    exam: Score
    passed: bool
    reason: str
    hold_r: float | None = None  # simply holding the coins over the hidden period, in R (same position size)
    pass_kind: str = ""  # "profit" (made money) | "beat_hold" (lost much less than the coins fell) | ""


@dataclass(frozen=True)
class Report:
    cutoff: pd.Timestamp
    practice_period: tuple[pd.Timestamp, pd.Timestamp]
    exam_period: tuple[pd.Timestamp, pd.Timestamp]
    settings_tested: int
    settings_eligible: int
    winners: list[Result]
    current: Result | None
    chosen: Setting | None
    market_ok: pd.Series | None = None  # the market mood filter used, if any
    hold_returns: dict[str, float] | None = None  # each coin's own return over the hidden period
    shorts: bool = False  # short selling was included

    def to_text(self, risk_per_trade: float = 250.0) -> str:
        d = lambda t: t.strftime("%Y-%m-%d")  # noqa: E731
        lines = [
            f"Practice years : {d(self.practice_period[0])} → {d(self.practice_period[1])}",
            f"Hidden year    : {d(self.exam_period[0])} → {d(self.exam_period[1])}  (not looked at while searching)",
            f"Settings tested: {self.settings_tested}  (enough trades and profitable in practice: {self.settings_eligible})",
            "",
            "Top settings from practice, then their result on the hidden year:",
        ]
        rows = list(self.winners) + ([self.current] if self.current else [])
        for i, r in enumerate(rows):
            tag = "current " if r is self.current else f"#{i + 1}      "
            lines.append(
                f"  {tag} {r.setting.label()}\n"
                f"           practice: {r.practice.trades:4d} trades, win {r.practice.win_rate:5.1%}, {r.practice.total_r:+7.1f} R (₹{r.practice.rupees(risk_per_trade):+,.0f})\n"
                f"           hidden  : {r.exam.trades:4d} trades, win {r.exam.win_rate:5.1%}, {r.exam.total_r:+7.1f} R (₹{r.exam.rupees(risk_per_trade):+,.0f})"
                f"  → {'PASS' if r.passed else 'FAIL'}: {r.reason}"
                + (f"\n           holding the coins instead: {r.hold_r:+7.1f} R" if r.hold_r is not None else "")
            )
        lines.append("")
        if self.chosen:
            lines.append(f"Chosen: {self.chosen.label()}")
        else:
            lines.append("Chosen: none. No winner held up on the hidden year, so keep the current settings.")
        return "\n".join(lines)


def judge(practice: Score, exam: Score, min_exam_trades: int, min_edge_kept: float,
          hold: float | None = None, max_loss_vs_hold: float | None = None) -> tuple[bool, str, str]:
    """(passed, why, pass kind). `hold`: buy-and-hold result in R over the same hidden period.
    `max_loss_vs_hold`: fairer exam. In a falling market a setting also passes if its loss is at most
    this share of what holding the coins lost (0.25 = lost at most a quarter as much)."""
    if exam.trades < min_exam_trades:
        return False, f"only {exam.trades} trades in the hidden year (need {min_exam_trades})", ""
    if exam.total_r <= 0:
        if max_loss_vs_hold is not None and hold is not None and hold < 0:
            share = -exam.total_r / -hold
            if share <= max_loss_vs_hold:
                return True, (f"lost {-exam.total_r:.1f} R while holding the coins lost {-hold:.1f} R "
                              f"({share:.0%} of it, allowed {max_loss_vs_hold:.0%})"), "beat_hold"
            return False, f"lost {-exam.total_r:.1f} R; holding lost {-hold:.1f} R, so it only saved {1 - share:.0%} (need {1 - max_loss_vs_hold:.0%})", ""
        return False, "lost money in the hidden year", ""
    if practice.avg_r > 0 and exam.avg_r < min_edge_kept * practice.avg_r:
        return False, f"kept only {exam.avg_r / practice.avg_r:.0%} of its practice edge (need {min_edge_kept:.0%})", ""
    return True, "still profitable on unseen data", "profit"


def optimize(
    data: Mapping[str, pd.DataFrame],
    grid: Sequence[Setting] | None = None,
    *,
    holdout_days: int = 365,
    top_k: int = 5,
    min_practice_trades: int = 30,
    min_exam_trades: int = 5,
    min_edge_kept: float = 0.5,
    current: Setting | None = None,
    costs: Costs = Costs(),
    market_filter: pd.DataFrame | None = None,
    market_ma_days: int = 200,
    max_loss_vs_hold: float | None = 0.25,
    shorts: bool = False,
) -> Report:
    """`market_filter`: candles of the market leader (e.g. BTCUSDT). When given, new buys are only
    allowed while it is above its `market_ma_days` average (roadmap step 1).
    `max_loss_vs_hold`: fairer exam (roadmap step 3); None switches it off (profit required).
    `shorts`: also short sell while the market is falling (roadmap step 2); needs `market_filter`."""
    if shorts and market_filter is None:
        raise ValueError("short selling needs the market mood filter")
    grid = list(grid or build_grid())
    practice, cutoff = split_hidden_year(data, holdout_days)
    market_ok = market_mood(market_filter, market_ma_days) if market_filter is not None else None
    hidden = HiddenYear(data, cutoff, costs, max_exam_settings=top_k + 1, market_ok=market_ok, shorts=shorts)

    # Step 2: search on practice years only. `practice` physically excludes the hidden year.
    scores = run_grid(practice, grid, costs, market_ok=market_ok, shorts=shorts)
    eligible = [(s, sc) for s, sc in zip(grid, scores) if sc.trades >= min_practice_trades and sc.avg_r > 0]
    eligible.sort(key=lambda x: x[1].total_r, reverse=True)
    # Settings that produced exactly the same trades are one winner, not several.
    top: list[tuple[Setting, Score]] = []
    seen: set[tuple[int, float]] = set()
    for s, sc in eligible:
        key = (sc.trades, round(sc.total_r, 6))
        if key not in seen:
            seen.add(key)
            top.append((s, sc))
        if len(top) == top_k:
            break

    # Step 3: open the exam once, for the winners (and the current setting, as a baseline).
    exam_settings = [s for s, _ in top] + ([current] if current else [])
    exam_scores = hidden.exam(exam_settings) if exam_settings else []

    held = hold_returns(data, cutoff, costs)

    def result(s: Setting, p: Score, e: Score) -> Result:
        h = hold_r(held, s.stop_loss_pct) if held else None
        ok, why, kind = judge(p, e, min_exam_trades, min_edge_kept, h, max_loss_vs_hold)
        return Result(s, p, e, ok, why, h, kind)

    winners = [result(s, p, e) for (s, p), e in zip(top, exam_scores)]
    current_result = None
    if current:
        cur_practice = run_grid(practice, [current], costs, market_ok=market_ok, shorts=shorts)[0]
        current_result = result(current, cur_practice, exam_scores[-1])

    # Step 4: best practice rank that made money in the exam. The exam never re-orders the winners.
    # A "lost less than holding" pass counts only when nothing made money, and only replaces the
    # current setting if that one did worse in the hidden period (a switch must never be a step down).
    chosen = next((r.setting for r in winners if r.pass_kind == "profit"), None)
    if chosen is None:
        chosen = next((r.setting for r in winners if r.pass_kind == "beat_hold"
                       and (current_result is None or current_result.exam.total_r < r.exam.total_r)), None)

    first = min(df.index.min() for df in data.values())
    last = max(df.index.max() for df in data.values())
    return Report(cutoff, (first, cutoff), (cutoff + pd.Timedelta(days=1), last), len(grid), len(eligible), winners, current_result, chosen,
                  market_ok, held, shorts)


def setting_from_config(cfg: AgentConfig) -> Setting:
    t = cfg.technical
    return Setting(t.trend_window, t.breakout_window, tuple(x for x in ALL_TRIGGERS if x in t.triggers), cfg.risk.stop_loss_pct)


def apply_setting(cfg: AgentConfig, s: Setting) -> AgentConfig:
    """New AgentConfig using the chosen setting; everything else (risk budget etc.) unchanged."""
    return replace(
        cfg,
        technical=TechnicalConfig(s.trend_window, s.breakout_window, frozenset(s.triggers)),
        risk=replace(cfg.risk, stop_loss_pct=s.stop_loss_pct),
    )
