"""Watch state: news hypotheses held until technical confirmation arrives or they age out."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..config import AgentConfig
from ..models import Action, Snapshot


@dataclass
class WatchEntry:
    symbol: str
    action: Action
    snapshot: Snapshot
    opened_at: datetime
    expires_at: datetime
    event_type: str
    sector: str


class WatchList:
    def __init__(self, cfg: AgentConfig) -> None:
        self._cfg = cfg
        self._entries: dict[str, WatchEntry] = {}

    def window_for(self, sector: str, event_type: str) -> float:
        w = self._cfg.watch_windows_s
        return w.get((sector, event_type), w.get(("*", event_type), w.get((sector, "*"), self._cfg.default_watch_window_s)))

    def add(self, snapshot: Snapshot, action: Action, now: datetime) -> WatchEntry:
        existing = self._entries.get(snapshot.symbol)
        if existing and existing.action == action:
            existing.snapshot = snapshot  # refresh the evidence, keep the original clock
            return existing
        event_type = snapshot.news.event_type if snapshot.news else "general"
        entry = WatchEntry(
            symbol=snapshot.symbol,
            action=action,
            snapshot=snapshot,
            opened_at=now,
            expires_at=now + timedelta(seconds=self.window_for(snapshot.sector, event_type)),
            event_type=event_type,
            sector=snapshot.sector,
        )
        self._entries[snapshot.symbol] = entry
        return entry

    def get(self, symbol: str) -> WatchEntry | None:
        return self._entries.get(symbol)

    def resolve(self, symbol: str) -> WatchEntry | None:
        return self._entries.pop(symbol, None)

    def expire(self, now: datetime) -> list[WatchEntry]:
        """Drop and return entries past their window (treated as non-events)."""
        gone = [e for e in self._entries.values() if now >= e.expires_at]
        for e in gone:
            del self._entries[e.symbol]
        return gone

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(list(self._entries.values()))
