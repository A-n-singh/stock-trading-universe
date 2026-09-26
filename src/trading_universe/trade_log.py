"""Append-only trade log: snapshot acted on, its rationale, the decision and the eventual outcome.

This closes the mistake loop (SDD) and is the raw input to the retraining pipeline (TDD).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Action, TradeDecision


@dataclass
class TradeRecord:
    trade_id: str
    symbol: str
    action: str
    quantity: float
    entry_price: float
    stop_price: float
    risk_amount: float
    opened_at: str
    snapshot: dict[str, Any]
    votes: list[dict[str, Any]]
    exit_price: float | None = None
    closed_at: str | None = None
    exit_reason: str | None = None
    pnl: float | None = None
    fees: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)  # what the decision model saw (training input)

    @property
    def closed(self) -> bool:
        return self.closed_at is not None

    @property
    def sector(self) -> str:
        return self.snapshot.get("sector", "unknown")

    @property
    def event_type(self) -> str:
        return (self.snapshot.get("news") or {}).get("event_type", "general")


class TradeLog:
    """In-memory index backed by an optional JSONL file (one line per open/close event)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._records: dict[str, TradeRecord] = {}
        if self.path and self.path.exists():
            self._load()

    def _load(self) -> None:
        assert self.path
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev["event"] == "open":
                self._records[ev["trade_id"]] = TradeRecord(**ev["record"])
            elif ev["event"] == "close" and ev["trade_id"] in self._records:
                for k, v in ev["fields"].items():
                    setattr(self._records[ev["trade_id"]], k, v)

    def _append(self, event: dict[str, Any]) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(event) + "\n")

    def record_open(self, trade_id: str, decision: TradeDecision, fill_price: float, fee: float,
                    context: dict[str, Any] | None = None) -> TradeRecord:
        rec = TradeRecord(
            trade_id=trade_id,
            symbol=decision.symbol,
            action=decision.action.value,
            quantity=decision.quantity,
            entry_price=fill_price,
            stop_price=decision.stop_price,
            risk_amount=decision.risk_amount,
            opened_at=decision.decided_at.isoformat(),
            snapshot=decision.snapshot.to_dict(),
            votes=[{"name": v.name, "approve": v.approve, "reason": v.reason, "details": v.details} for v in decision.votes],
            fees=fee,
            context=context or {},
        )
        self._records[trade_id] = rec
        self._append({"event": "open", "trade_id": trade_id, "record": rec.__dict__})
        return rec

    def record_close(self, trade_id: str, exit_price: float, closed_at: datetime, reason: str, fee: float) -> TradeRecord:
        rec = self._records[trade_id]
        sign = 1 if rec.action == Action.BUY.value else -1
        fields = {
            "exit_price": exit_price,
            "closed_at": closed_at.isoformat(),
            "exit_reason": reason,
            "fees": rec.fees + fee,
            "pnl": sign * (exit_price - rec.entry_price) * rec.quantity - (rec.fees + fee),
        }
        for k, v in fields.items():
            setattr(rec, k, v)
        self._append({"event": "close", "trade_id": trade_id, "fields": fields})
        return rec

    def open_trades(self) -> list[TradeRecord]:
        return [r for r in self._records.values() if not r.closed]

    def closed_trades(self) -> list[TradeRecord]:
        return [r for r in self._records.values() if r.closed]

    def all(self) -> list[TradeRecord]:
        return list(self._records.values())


@dataclass
class RefinementTask:
    """Scoped task routed back to the owning team lead when its cluster keeps missing."""

    sector: str
    event_type: str
    losses: int
    sample: int
    trade_ids: list[str] = field(default_factory=list)


def refinement_tasks(log: TradeLog, window: int = 20, min_sample: int = 5, max_loss_rate: float = 0.6) -> list[RefinementTask]:
    """Find (sector, event_type) clusters whose recent loss rate is too high — a scoped fix, not a global audit."""
    groups: dict[tuple[str, str], list[TradeRecord]] = defaultdict(list)
    for r in sorted(log.closed_trades(), key=lambda r: r.closed_at or ""):
        groups[(r.sector, r.event_type)].append(r)
    tasks = []
    for (sector, event_type), recs in groups.items():
        recent = recs[-window:]
        losses = [r for r in recent if (r.pnl or 0) < 0]
        if len(recent) >= min_sample and len(losses) / len(recent) > max_loss_rate:
            tasks.append(RefinementTask(sector, event_type, len(losses), len(recent), [r.trade_id for r in losses]))
    return tasks
