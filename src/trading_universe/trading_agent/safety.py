"""Daily stop (TDD "Kill switch"): no new trades for the rest of the day once the day's losses reach the limit.

The day's result counts both closed and still-open trades (the account value now vs at the start of the
day, in UTC), measured against the account itself, so the limit grows and shrinks with the account. Open
trades keep their stop-losses and are still managed while the stop is on. It resets at the next day.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class DailyStop:
    limit: float = 0.02  # 2% of the account's value at the start of the day
    day: str = ""
    start_equity: float = 0.0
    last_equity: float = 0.0
    tripped_at: str | None = None

    def check(self, equity: float, now: datetime) -> bool:
        """Update with the account value now; True while new trades are stopped for the day."""
        today = now.date().isoformat()
        if today != self.day or self.start_equity <= 0:
            self.day, self.start_equity, self.tripped_at = today, equity, None
        self.last_equity = equity
        if self.tripped_at is None and self.start_equity > 0 and equity <= self.start_equity * (1 - self.limit):
            self.tripped_at = now.isoformat()
        return self.tripped_at is not None

    @property
    def day_result_pct(self) -> float:
        return (self.last_equity / self.start_equity - 1) * 100 if self.start_equity > 0 else 0.0

    def state(self) -> dict:
        return asdict(self) | {"day_result_pct": round(self.day_result_pct, 2)}

    @classmethod
    def restore(cls, state: dict, limit: float) -> DailyStop:
        keep = {k: state[k] for k in ("day", "start_equity", "last_equity", "tripped_at") if k in state}
        return cls(limit=limit, **keep)
