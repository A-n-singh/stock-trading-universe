"""Team Lead routing for the slow research loop (SDD §Team Lead layer).

Each team lead carries a compact semantic fingerprint (a few embedding vectors). A task is
routed by vector similarity — no LLM call — and only escalates to an LLM judgement when it
falls below the threshold for every active lead. Idle leads go dormant (archived, not deleted)
and are rehydrated when a similar task resurfaces.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..memory.shared import SharedMemory
from ..memory.vectors import Vector, cosine

Embedder = Callable[[str], Vector]
# Called only below threshold: returns the name of an existing lead the task belongs to,
# or None if the task is genuinely new and needs a new lead.
Escalation = Callable[[str, list[str]], str | None]


@dataclass
class TeamLead:
    name: str
    domain: str  # news_sentiment | price_technical | risk_portfolio
    fingerprint: list[list[float]]
    last_matched: datetime
    max_fingerprint: int = 8
    dormant: bool = False
    tasks_handled: int = 0

    def similarity(self, v: Vector) -> float:
        return max((cosine(v, f) for f in self.fingerprint), default=0.0)

    def absorb(self, v: Vector, now: datetime) -> None:
        self.last_matched = now
        self.tasks_handled += 1
        if len(self.fingerprint) < self.max_fingerprint:
            self.fingerprint.append(list(v))


@dataclass
class RouteResult:
    lead: TeamLead
    similarity: float
    how: str  # matched | rehydrated | escalated_existing | spawned


@dataclass
class TeamLeadRouter:
    embed: Embedder
    escalate: Escalation
    threshold: float = 0.8
    dormancy_after: timedelta = timedelta(weeks=3)
    leads: dict[str, TeamLead] = field(default_factory=dict)
    # Spawn approval goes through the domain manager, not the Orchestrator.
    approve_spawn: Callable[[str, str], bool] = lambda domain, name: True
    # When set, a lead's shelf in the shared memory goes dormant / wakes up together with the lead.
    memory: SharedMemory | None = None

    def _wake(self, lead: TeamLead) -> None:
        lead.dormant = False
        if self.memory is not None:
            self.memory.rehydrate(lead.name)

    def add_lead(self, name: str, domain: str, seed_descriptions: Sequence[str], now: datetime) -> TeamLead:
        lead = TeamLead(name, domain, [list(self.embed(d)) for d in seed_descriptions], now)
        self.leads[name] = lead
        return lead

    def route(self, task: str, domain: str, now: datetime) -> RouteResult | None:
        v = self.embed(task)
        candidates = [l for l in self.leads.values() if l.domain == domain]
        best = max(candidates, key=lambda l: l.similarity(v), default=None)
        if best is not None and best.similarity(v) >= self.threshold:
            how = "rehydrated" if best.dormant else "matched"
            self._wake(best)
            sim = best.similarity(v)
            best.absorb(v, now)
            return RouteResult(best, sim, how)

        choice = self.escalate(task, [l.name for l in candidates])
        if choice is not None and choice in self.leads:
            lead = self.leads[choice]
            self._wake(lead)
            sim = lead.similarity(v)
            lead.absorb(v, now)  # widen the fingerprint so the next rephrasing matches cheaply
            return RouteResult(lead, sim, "escalated_existing")

        name = f"{domain}:lead-{len(self.leads) + 1}"
        if not self.approve_spawn(domain, name):
            return None
        lead = TeamLead(name, domain, [list(v)], now, tasks_handled=1)
        self.leads[name] = lead
        return RouteResult(lead, 1.0, "spawned")

    def state(self) -> dict:
        """What the leads have learned (fingerprints, last activity, sleeping), for saving across restarts."""
        return {name: {"domain": l.domain, "fingerprint": l.fingerprint, "last_matched": l.last_matched.isoformat(),
                       "dormant": l.dormant, "tasks_handled": l.tasks_handled} for name, l in self.leads.items()}

    def restore(self, state: dict, keep_fingerprints: bool = True) -> None:
        """Load saved leads. `keep_fingerprints=False` when the embedder changed (old vectors don't compare)."""
        for name, d in state.items():
            lead = self.leads.get(name)
            if lead is None:
                if not keep_fingerprints:
                    continue  # a lead known only by old-style vectors can't be matched any more
                lead = self.leads[name] = TeamLead(name, d["domain"], [], datetime.fromisoformat(d["last_matched"]))
            if keep_fingerprints and d.get("fingerprint"):
                lead.fingerprint = [list(v) for v in d["fingerprint"]]
            lead.last_matched = datetime.fromisoformat(d["last_matched"])
            lead.dormant = bool(d.get("dormant"))
            lead.tasks_handled = int(d.get("tasks_handled", 0))
            if lead.dormant and self.memory is not None:
                self.memory.set_dormant(name)

    def sweep_dormant(self, now: datetime) -> list[TeamLead]:
        """Mark leads idle past the dormancy window as dormant (archived, still rehydratable)."""
        went = [l for l in self.leads.values() if not l.dormant and now - l.last_matched >= self.dormancy_after]
        for l in went:
            l.dormant = True
            if self.memory is not None:
                self.memory.set_dormant(l.name)
        return went
