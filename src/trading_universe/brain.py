"""The brain's learning core: what really moves prices.

Every signal the research team produces is written down — a scored news item, a chart signal from a
Price desk, a warning from a Risk desk — with its direction (up or down) and strength. Once 1 and 3
days have passed, the brain looks up what the price actually did ("settling" the signal). From the
settled signals it keeps a scorecard per desk and kind of signal:

  hit rate   how often the price moved the way the signal said (over 3 days)
  base rate  how often the price moved that way anyway (so a bullish signal in a rising market isn't
             mistaken for skill)
  edge       hit rate minus base rate
  weight     how much the research team trusts that kind of signal from now on: 1.0 = normal,
             up to 1.5 for signals with a proven edge, down to 0.5 for ones that keep being wrong.
             Few results count for little (the weight moves slowly until there are dozens).

No peeking: a signal only counts once its 3 days are over, so at any moment the weights use only what
had already happened (the time machine relies on this). `freeze()` stops learning, for exams.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HORIZONS = {"r1": timedelta(days=1), "r3": timedelta(days=3)}
MARKET_PROXY = "BTCUSDT"  # news about the whole market is checked against Bitcoin
SECTIONS = ("news", "price", "risk")


@dataclass(frozen=True)
class Signal:
    id: str
    at: str  # ISO time the signal was known
    section: str  # news | price | risk
    desk: str  # e.g. regulatory, trend, events
    kind: str  # e.g. listing, breakout, hack
    symbol: str  # coin, or MARKET
    direction: int  # +1 up, -1 down
    strength: float  # 0..1
    text: str = ""


@dataclass
class Card:
    section: str
    desk: str
    kind: str
    n: int = 0
    hits: int = 0
    base_hits: float = 0.0  # expected hits if the signal had no skill
    signed_r3: float = 0.0  # sum of direction * 3-day return
    symbols: dict[str, int] = field(default_factory=dict)

    @property
    def hit_rate(self) -> float:
        return self.hits / self.n if self.n else 0.0

    @property
    def base_rate(self) -> float:
        return self.base_hits / self.n if self.n else 0.0

    @property
    def edge(self) -> float:
        return self.hit_rate - self.base_rate

    @property
    def avg_move(self) -> float:
        return self.signed_r3 / self.n if self.n else 0.0

    @property
    def weight(self) -> float:
        shrink = self.n / (self.n + 30)  # 30 results count for half
        return round(min(1.5, max(0.5, 1 + 3 * self.edge * shrink)), 3)

    def row(self) -> dict:
        return {"section": self.section, "desk": self.desk, "kind": self.kind, "signals": self.n,
                "hit_rate": round(self.hit_rate, 3), "base_rate": round(self.base_rate, 3), "edge": round(self.edge, 3),
                "avg_move": round(self.avg_move, 4), "weight": self.weight, "symbols": self.symbols}


class Tally:
    """Running counts behind the scorecards, updated one settled signal at a time."""

    def __init__(self) -> None:
        self.up: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # symbol -> [rises, settled]
        self.stats: dict[tuple[str, str, str], dict] = {}

    def add(self, s: Signal, r3: float) -> None:
        u = self.up[s.symbol]
        u[0] += r3 > 0
        u[1] += 1
        st = self.stats.setdefault((s.section, s.desk, s.kind), {"n": 0, "hits": 0, "signed": 0.0, "dirs": {}})
        st["n"] += 1
        st["hits"] += s.direction * r3 > 0
        st["signed"] += s.direction * r3
        d = st["dirs"].setdefault(s.symbol, [0, 0])  # [up signals, down signals]
        d[0 if s.direction > 0 else 1] += 1

    def card(self, key: tuple[str, str, str]) -> Card:
        st = self.stats[key]
        base = 0.0
        for sym, (n_up, n_down) in st["dirs"].items():
            rises, total = self.up[sym]
            p_up = rises / total if total else 0.5
            base += n_up * p_up + n_down * (1 - p_up)
        return Card(*key, n=st["n"], hits=st["hits"], base_hits=base, signed_r3=st["signed"],
                    symbols={k: v[0] + v[1] for k, v in st["dirs"].items()})

    def rows(self) -> list[dict]:
        rows = [self.card(k).row() for k in self.stats]
        return sorted(rows, key=lambda r: (SECTIONS.index(r["section"]) if r["section"] in SECTIONS else 9, -r["signals"]))


def _ts(s: str) -> datetime:
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def close_series(frame: pd.DataFrame) -> pd.Series:
    """Closing prices indexed by the time each candle closed (UTC), from a frame indexed by open time."""
    idx = pd.DatetimeIndex(frame.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    step = (idx[1:] - idx[:-1]).median() if len(idx) > 1 else pd.Timedelta(days=1)
    return pd.Series(frame["close"].to_numpy(dtype=float), index=idx + step)


def move(closes: pd.Series, at: datetime, horizon: timedelta) -> float | None:
    """Return from the last close at or before `at` (the price when the signal was known) to the close
    `horizon` after that one; None if that close hasn't happened yet or there is no earlier close."""
    before = closes[closes.index <= pd.Timestamp(at)]
    if before.empty or before.iloc[-1] <= 0:
        return None
    after = closes[closes.index >= before.index[-1] + pd.Timedelta(horizon)]
    if after.empty:
        return None
    return float(after.iloc[0] / before.iloc[-1] - 1)


class Brain:
    """Signals, their outcomes and the scorecards. Files (when `folder` is given): signals.jsonl,
    outcomes.jsonl (both append-only)."""

    def __init__(self, folder: Path | None = None) -> None:
        self.folder = folder
        self.signals: dict[str, Signal] = {}
        self.outcomes: dict[str, dict[str, float]] = {}
        self._waiting: dict[str, Signal] = {}  # written down, not checked yet
        self.frozen_at: datetime | None = None
        self._frozen: dict[tuple[str, str, str], float] = {}
        self._tally = Tally()
        self._weights: dict[tuple[str, str, str], float] = {}
        if folder:
            folder.mkdir(parents=True, exist_ok=True)
            for line in self._lines("signals.jsonl"):
                sig = Signal(**line)
                self.signals[sig.id] = sig
            for line in self._lines("outcomes.jsonl"):
                self.outcomes[line["id"]] = {k: line[k] for k in HORIZONS}
            for sid, r in self.outcomes.items():
                if sid in self.signals:
                    self._tally.add(self.signals[sid], r["r3"])
            self._waiting = {k: v for k, v in self.signals.items() if k not in self.outcomes}
            self._refresh()

    def _lines(self, name: str) -> list[dict]:
        p = self.folder / name if self.folder else None
        if not p or not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def _append(self, name: str, rec: dict) -> None:
        if self.folder:
            with (self.folder / name).open("a") as f:
                f.write(json.dumps(rec) + "\n")

    # ---- writing down signals ------------------------------------------------------------

    def record(self, sig: Signal) -> bool:
        """Write a signal down once (the same news item or the same day's chart signal is not repeated)."""
        if sig.direction not in (1, -1) or sig.id in self.signals:
            return False
        self.signals[sig.id] = sig
        self._waiting[sig.id] = sig
        self._append("signals.jsonl", asdict(sig))
        return True

    # ---- learning from what happened -----------------------------------------------------

    def settle(self, closes_for: Callable[[str], pd.Series | None], now: datetime) -> int:
        """Look up the price moves of signals whose 3 days are over. Returns how many were settled."""
        due = [s for s in self._waiting.values() if _ts(s.at) + HORIZONS["r3"] <= now]
        cache: dict[str, pd.Series | None] = {}
        settled = 0
        for s in due:
            sym = MARKET_PROXY if s.symbol == "MARKET" else s.symbol
            if sym not in cache:
                c = closes_for(sym)
                cache[sym] = None if c is None else c[c.index <= pd.Timestamp(now)]  # never look past "now"
            closes = cache[sym]
            if closes is None or closes.empty:
                continue
            r = {k: move(closes, _ts(s.at), h) for k, h in HORIZONS.items()}
            if any(v is None for v in r.values()):
                continue
            self.outcomes[s.id] = r  # type: ignore[assignment]
            del self._waiting[s.id]
            self._tally.add(s, r["r3"])  # type: ignore[arg-type]
            self._append("outcomes.jsonl", {"id": s.id, **r})
            settled += 1
        if settled:
            self._refresh()
        return settled

    def _refresh(self) -> None:
        self._weights = {k: self._tally.card(k).weight for k in self._tally.stats}

    def freeze(self, at: datetime) -> None:
        """Stop learning: the trust weights stay as they are now (e.g. for the hidden exam period).
        Scorecards keep counting, so the exam can be measured."""
        self.frozen_at = at
        self._frozen = dict(self._weights)

    # ---- using what was learned ----------------------------------------------------------

    def weight(self, section: str, desk: str, kind: str) -> float:
        table = self._frozen if self.frozen_at is not None else self._weights
        return table.get((section, desk, kind), 1.0)

    def scorecard(self) -> list[dict]:
        return self._tally.rows()

    def scorecard_between(self, since: datetime | None = None, until: datetime | None = None) -> list[dict]:
        """Scorecards over the signals known in a time window only (e.g. the exam), with that window's base rates."""
        t = Tally()
        for sid, r in self.outcomes.items():
            s = self.signals.get(sid)
            if s and (since is None or _ts(s.at) >= since) and (until is None or _ts(s.at) < until):
                t.add(s, r["r3"])
        return t.rows()

    def summary(self) -> dict:
        return {"signals": len(self.signals), "settled": len(self.outcomes), "waiting": len(self.signals) - len(self.outcomes),
                "frozen_at": self.frozen_at.isoformat() if self.frozen_at else None}
