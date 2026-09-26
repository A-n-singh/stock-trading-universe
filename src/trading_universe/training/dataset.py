"""Training data for the decision model (TDD): snapshot -> decision -> outcome.

Three sources, all in the same three-part format (context / question / output):
  - historical bootstrap: every day in years of price history where the price rules fired,
    plus any news that was already public that day; the outcome already happened, so the label is fact;
  - logged snapshots from the research loop, labelled with what the price did next;
  - closed paper/live trades from the trade log.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import timezone
from pathlib import Path

import pandas as pd

from ..models import Candle, Snapshot
from ..news.store import NewsStore
from .features import decision_context
from .schema import GATE_QUESTIONS, Output, TrainingExample

QUESTION = GATE_QUESTIONS["trade"]
SYSTEM = ("You are the Trading Agent's decision model. Read the context and answer the question with one of the "
          "allowed answers and a confidence between 0 and 1. Reply with JSON only.")


def simulate_long(df: pd.DataFrame, i: int, stop_pct: float, max_days: int, fee: float = 0.001) -> tuple[float, str]:
    """R-multiple of buying at close i: stop-loss at -stop_pct, else sell after max_days. (R, exit reason)."""
    entry = df["close"].iloc[i]
    stop = entry * (1 - stop_pct)
    last = min(len(df) - 1, i + max_days)
    for j in range(i + 1, last + 1):
        if df["low"].iloc[j] <= stop:
            exit_px = min(stop, df["open"].iloc[j])
            return ((exit_px / entry - 1) - 2 * fee) / stop_pct, "stop_loss"
    return ((df["close"].iloc[last] / entry - 1) - 2 * fee) / stop_pct, "time"


def label(r: float, win_r: float = 0.3) -> Output:
    """What the agent should have done: buy if it paid at least win_r R, otherwise hold.
    Confidence grows with how clear the outcome was."""
    answer = "buy" if r >= win_r else "hold"
    return Output(answer, round(max(0.5, min(0.95, 0.5 + 0.15 * abs(r))), 3))


def _candles(df: pd.DataFrame, upto: int, keep: int = 250) -> list[Candle]:
    part = df.iloc[max(0, upto - keep + 1): upto + 1]
    return [Candle(ts.to_pydatetime(), r.open, r.high, r.low, r.close, r.volume) for ts, r in zip(part.index, part.itertuples())]


def _news_snapshot(news: NewsStore | None, symbol: str, ts: pd.Timestamp) -> Snapshot | None:
    """A minimal snapshot from news that was public at `ts` (never later: no peeking)."""
    if news is None:
        return None
    from ..models import AssetClass, Direction, NewsSignal
    from ..research.sentiment import KeywordScorer, lead_for

    t = ts.to_pydatetime().replace(tzinfo=timezone.utc)
    items = news.items(symbol=symbol, since=t - pd.Timedelta(hours=24), until=t)
    if not items:
        return None
    s = KeywordScorer().score(items[0], symbol, lead_for(items[0]))
    return Snapshot(symbol, s.direction, s.confidence, t, AssetClass.CRYPTO,
                    news=NewsSignal(s.direction, s.magnitude, s.confidence, s.item.event_type, s.actionable, s.item.title))


def examples_from_history(
    frames: Mapping[str, pd.DataFrame],
    entries: Mapping[str, pd.Series],
    news: NewsStore | None = None,
    stop_pct: float = 0.03,
    max_days: int = 10,
) -> list[TrainingExample]:
    """Historical bootstrap. `entries[symbol]` marks the days the price rules fired (e.g. long_signals)."""
    out = []
    for sym, df in frames.items():
        sig = entries[sym].reindex(df.index).fillna(False).to_numpy(dtype=bool)
        for i in range(len(df) - 1):
            if not sig[i]:
                continue
            r, why = simulate_long(df, i, stop_pct, max_days)
            ts = df.index[i]
            ctx = decision_context(_news_snapshot(news, sym, ts), _candles(df, i), sym)
            out.append(TrainingExample(ctx, QUESTION, label(r), {
                "source": "history", "symbol": sym, "time": ts.isoformat(), "taken_action": "buy",
                "pnl": r, "risk_amount": 1.0, "exit": why, "closed_at": (ts + pd.Timedelta(days=max_days)).isoformat(),
            }))
    return sorted(out, key=lambda e: e.meta["time"])


def examples_from_snapshots(
    snapshots: Iterable[Snapshot], frames: Mapping[str, pd.DataFrame], stop_pct: float = 0.03, max_days: int = 10,
) -> list[TrainingExample]:
    """Label each logged research snapshot with what the price did after it."""
    out = []
    for snap in snapshots:
        df = frames.get(snap.symbol)
        if df is None:
            continue
        ts = pd.Timestamp(snap.as_of).tz_convert(None)
        idx = df.index.searchsorted(ts, side="right") - 1  # last candle known at snapshot time
        if idx < 20 or idx + max_days >= len(df):
            continue  # not enough history before, or the future isn't known yet
        r, why = simulate_long(df, idx, stop_pct, max_days)
        out.append(TrainingExample(decision_context(snap, _candles(df, idx), snap.symbol), QUESTION, label(r), {
            "source": "snapshot", "symbol": snap.symbol, "time": ts.isoformat(), "taken_action": "buy",
            "pnl": r, "risk_amount": 1.0, "exit": why, "closed_at": df.index[idx + max_days].isoformat(),
        }))
    return sorted(out, key=lambda e: e.meta["time"])


def to_chat(ex: TrainingExample) -> dict:
    """Prompt/completion rows in chat format (what TRL's trainers and chat models expect)."""
    return {
        "prompt": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": ex.prompt()}],
        "completion": [{"role": "assistant", "content": ex.target()}],
        "label": ex.output.answer,
        "pnl_r": float(ex.meta.get("pnl", 0.0)) / float(ex.meta.get("risk_amount", 1.0) or 1.0),
        "taken_action": ex.meta.get("taken_action", "buy"),
        "time": str(ex.meta.get("time") or ex.meta.get("closed_at", "")),
        # raw fields, so the example can be rebuilt for evaluation
        "context": ex.context,
        "output": {"answer": ex.output.answer, "confidence": ex.output.confidence},
        "meta": {k: (float(v) if hasattr(v, "item") else v) for k, v in ex.meta.items()},
    }


def read_examples(path: str | Path) -> list[TrainingExample]:
    out = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out.append(TrainingExample(r["context"], QUESTION, Output(r["output"]["answer"], r["output"]["confidence"]), r["meta"]))
    return out


def write_jsonl(examples: Sequence[TrainingExample], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(to_chat(e)) + "\n" for e in examples))
    return p


def split_by_time(examples: Sequence[TrainingExample], holdout_fraction: float = 0.2) -> tuple[list, list]:
    """Oldest part for training, newest for testing: the model must work forward in time."""
    ordered = sorted(examples, key=lambda e: e.meta.get("time") or e.meta.get("closed_at", ""))
    cut = int(len(ordered) * (1 - holdout_fraction))
    return ordered[:cut], ordered[cut:]
