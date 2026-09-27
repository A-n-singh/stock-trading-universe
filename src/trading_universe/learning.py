"""Mistake-loop closure (SDD): every closed trade feeds back into the slow research loop.

For each newly closed trade:
  1. its outcome goes into the memory diary (proof for future lessons),
  2. existing lessons from the responsible team lead get a win/loss (bad lessons retire themselves),
  3. once a team lead has enough trades of one kind, a new proven lesson is written,
  4. the coin's shelf gets a note linking to that lesson,
  5. clusters that keep losing get a scoped refinement: their news confidence is cut until they recover.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .memory.event_log import MarketEvent
from .memory.shared import Kind, SharedMemory
from .research.sentiment import LEAD_BY_NAME, lead_for_event
from .trade_log import RefinementTask, TradeLog, TradeRecord, refinement_tasks


class Refinements:
    """Per (sector, event type) confidence multipliers the cluster agents apply to news.

    With `require_approval` (the live system), a cut is only a proposal until the owner accepts it
    on the Agents page; `approved` then holds the accepted (or rejected = 1.0) multipliers."""

    def __init__(self, path: Path | None = None, require_approval: bool = False) -> None:
        self.path = path
        self.require_approval = require_approval
        self.multipliers: dict[str, float] = {}
        self.proposed: dict[str, dict] = {}
        self.approved: dict[str, float] = {}
        self.tasks: list[dict] = []
        if path and path.exists():
            d = json.loads(path.read_text())
            self.multipliers, self.tasks = d.get("multipliers", {}), d.get("tasks", [])
            self.proposed = d.get("proposed", {})

    @staticmethod
    def key(sector: str, event_type: str) -> str:
        return f"{sector}:{event_type}"

    def factor(self, sector: str, event_type: str) -> float:
        k = self.key(sector, event_type)
        if self.require_approval:
            return self.approved.get(k, 1.0)
        return self.multipliers.get(k, 1.0)

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"multipliers": self.multipliers, "proposed": self.proposed,
                                             "tasks": self.tasks[-200:]}, indent=1))


@dataclass
class LearnReport:
    trades_learned: int = 0
    outcomes_recorded: int = 0
    lessons_written: list[str] = field(default_factory=list)
    refinements: list[RefinementTask] = field(default_factory=list)


class MistakeLoop:
    def __init__(self, memory: SharedMemory, trade_log: TradeLog, refinements: Refinements, state_path: Path | None = None,
                 min_trades_for_lesson: int = 3, min_agreement: float = 2 / 3) -> None:
        self.memory, self.log, self.refinements = memory, trade_log, refinements
        self.state_path = state_path
        self.min_trades, self.min_agreement = min_trades_for_lesson, min_agreement
        self.learned: set[str] = set()
        if state_path and state_path.exists():
            self.learned = set(json.loads(state_path.read_text()))

    def _save_state(self) -> None:
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(sorted(self.learned)))

    @staticmethod
    def _r(rec: TradeRecord) -> float:
        return (rec.pnl or 0.0) / rec.risk_amount if rec.risk_amount else 0.0

    def run(self, now: datetime) -> LearnReport:
        report = LearnReport()
        new = [r for r in self.log.closed_trades() if r.trade_id not in self.learned]
        for rec in sorted(new, key=lambda r: r.closed_at or ""):
            closed = datetime.fromisoformat(rec.closed_at)  # type: ignore[arg-type]
            eid = f"trade:{rec.trade_id}"
            if self.memory.events.get(eid) is None:
                self.memory.events.append(MarketEvent(
                    eid, rec.symbol, closed, "trade_outcome",
                    f"{rec.action} {rec.symbol} after {rec.event_type} news: {'won' if (rec.pnl or 0) > 0 else 'lost'} {self._r(rec):+.2f} R",
                    rec.sector, {"pnl": rec.pnl, "r": self._r(rec), "event_type": rec.event_type, "exit_reason": rec.exit_reason},
                ))
            lead = lead_for_event(rec.event_type)
            writer = self.memory.for_agent(f"lead:{lead.name}", writes={lead.name})
            for hit in self.memory.recall(rec.snapshot.get("news", {}).get("headline", "") or rec.event_type, kind=Kind.PATTERN,
                                          as_of=closed, owner_id=lead.name, top_k=3):
                if hit.score >= 0.3 and hit.record.metadata.get("event_type") == rec.event_type:
                    writer.record_outcome(hit.record.id, closed, (rec.pnl or 0) > 0, rec.trade_id)
                    report.outcomes_recorded += 1
            self.learned.add(rec.trade_id)
            report.trades_learned += 1

        if new:
            report.lessons_written = self._write_lessons(now)
            report.refinements = self._refine(now)
        self._save_state()
        return report

    def _write_lessons(self, now: datetime) -> list[str]:
        groups: dict[tuple[str, str, str], list[TradeRecord]] = defaultdict(list)
        for r in self.log.closed_trades():
            groups[(r.event_type, r.sector, r.action)].append(r)
        written = []
        for (event_type, sector, action), recs in groups.items():
            if len(recs) < self.min_trades:
                continue
            wins = sum((r.pnl or 0) > 0 for r in recs)
            share = max(wins, len(recs) - wins) / len(recs)
            if share < self.min_agreement:
                continue  # no consistent pattern yet
            avg_r = sum(self._r(r) for r in recs) / len(recs)
            verdict = "usually worked" if wins * 2 > len(recs) else "usually failed"
            text = (f"{action.upper()} trades after {event_type} news on {sector} coins {verdict}: "
                    f"{wins}/{len(recs)} won, average {avg_r:+.2f} R")
            lead = lead_for_event(event_type)
            writer = self.memory.for_agent(f"lead:{lead.name}", writes={lead.name})
            evidence = [f"trade:{r.trade_id}" for r in recs]
            rec = writer.add_pattern(lead.name, text, evidence, now, {"event_type": event_type, "sector": sector, "action": action})
            written.append(rec.text)
            for sym in {r.symbol for r in recs}:
                mine = [r for r in recs if r.symbol == sym]
                w = sum((r.pnl or 0) > 0 for r in mine)
                self.memory.for_agent(f"cluster:{sym}", writes={sym}).add_asset_note(
                    sym, f"{sym}: {w}/{len(mine)} {action} trades after {event_type} news won", [rec.id], now)
        return written

    def _refine(self, now: datetime) -> list[RefinementTask]:
        tasks = refinement_tasks(self.log)
        losing = {Refinements.key(t.sector, t.event_type) for t in tasks}
        ref = self.refinements
        for t in tasks:
            k = Refinements.key(t.sector, t.event_type)
            if ref.require_approval:
                if k not in ref.proposed:  # a suggestion for the owner, not applied until accepted
                    ref.proposed[k] = {"since": now.isoformat(), "lead": lead_for_event(t.event_type).name, "sector": t.sector,
                                       "event_type": t.event_type, "losses": t.losses, "sample": t.sample, "multiplier": 0.6}
                continue
            if k not in ref.multipliers:
                ref.tasks.append({"at": now.isoformat(), "lead": lead_for_event(t.event_type).name, "sector": t.sector,
                                  "event_type": t.event_type, "losses": t.losses, "sample": t.sample,
                                  "action": "news confidence cut to 60% for this cluster"})
            ref.multipliers[k] = 0.6
        for k in list(ref.multipliers):  # recovered clusters go back to normal
            if k not in losing:
                del ref.multipliers[k]
        for k in list(ref.proposed):  # a suggestion for a cluster that recovered is withdrawn
            if k not in losing:
                del ref.proposed[k]
        self.refinements.save()
        return tasks


__all__ = ["LEAD_BY_NAME", "LearnReport", "MistakeLoop", "Refinements"]
