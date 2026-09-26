"""Shelf 1 — the diary: every market event exactly as it happened. Append-only, never edited."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MarketEvent:
    event_id: str
    symbol: str
    ts: datetime  # when the event happened
    event_type: str  # earnings, regulatory, social, price, trade ...
    text: str
    sector: str = "unknown"
    # Filled in later by a separate outcome event, never by editing this one.
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return json.dumps(d)

    @classmethod
    def from_json(cls, line: str) -> MarketEvent:
        d = json.loads(line)
        d["ts"] = datetime.fromisoformat(d["ts"])
        return cls(**d)


class EventLog:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._events: dict[str, MarketEvent] = {}
        if self.path and self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    ev = MarketEvent.from_json(line)
                    self._events[ev.event_id] = ev

    def append(self, event: MarketEvent) -> MarketEvent:
        if event.event_id in self._events:
            raise ValueError(f"event {event.event_id} already logged; the diary is never rewritten")
        self._events[event.event_id] = event
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(event.to_json() + "\n")
        return event

    def get(self, event_id: str) -> MarketEvent | None:
        return self._events.get(event_id)

    def events(self, *, symbol: str | None = None, as_of: datetime | None = None) -> list[MarketEvent]:
        out = [
            e
            for e in self._events.values()
            if (symbol is None or e.symbol == symbol) and (as_of is None or e.ts <= as_of)
        ]
        return sorted(out, key=lambda e: e.ts)

    def __len__(self) -> int:
        return len(self._events)
