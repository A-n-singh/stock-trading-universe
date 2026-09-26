"""Team Lead routing for the slow research loop (SDD §Team Lead layer).

Each team lead carries a compact semantic fingerprint (a few embedding vectors). A task is
routed by vector similarity — no LLM call — and only escalates to an LLM judgement when it
falls below the threshold for every active lead. Idle leads go dormant (archived, not deleted)
and are rehydrated when a similar task resurfaces.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

Vector = Sequence[float]
Embedder = Callable[[str], Vector]
# Called only below threshold: returns the name of an existing lead the task belongs to,
# or None if the task is genuinely new and needs a new lead.
Escalation = Callable[[str, list[str]], str | None]


def cosine(a: Vector, b: Vector) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


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
            best.dormant = False
            sim = best.similarity(v)
            best.absorb(v, now)
            return RouteResult(best, sim, how)

        choice = self.escalate(task, [l.name for l in candidates])
        if choice is not None and choice in self.leads:
            lead = self.leads[choice]
            lead.dormant = False
            sim = lead.similarity(v)
            lead.absorb(v, now)  # widen the fingerprint so the next rephrasing matches cheaply
            return RouteResult(lead, sim, "escalated_existing")

        name = f"{domain}:lead-{len(self.leads) + 1}"
        if not self.approve_spawn(domain, name):
            return None
        lead = TeamLead(name, domain, [list(v)], now, tasks_handled=1)
        self.leads[name] = lead
        return RouteResult(lead, 1.0, "spawned")

    def sweep_dormant(self, now: datetime) -> list[TeamLead]:
        """Mark leads idle past the dormancy window as dormant (archived, still rehydratable)."""
        went = [l for l in self.leads.values() if not l.dormant and now - l.last_matched >= self.dormancy_after]
        for l in went:
            l.dormant = True
        return went
