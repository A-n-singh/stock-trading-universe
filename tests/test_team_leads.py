from __future__ import annotations

from datetime import timedelta

from conftest import NOW
from trading_universe.research.team_leads import TeamLeadRouter

VOCAB = ["earnings", "profit", "revenue", "sebi", "regulator", "fine", "reddit", "twitter", "hype"]


def embed(text: str) -> list[float]:
    words = text.lower().split()
    return [float(sum(w.startswith(v) for w in words)) for v in VOCAB]


def router(escalate=lambda task, names: None) -> TeamLeadRouter:
    r = TeamLeadRouter(embed=embed, escalate=escalate, threshold=0.7)
    r.add_lead("earnings", "news", ["earnings profit revenue"], NOW)
    r.add_lead("regulatory", "news", ["sebi regulator fine"], NOW)
    return r


def test_routes_by_similarity_without_escalation():
    calls = []
    r = router(lambda t, n: calls.append(t))
    res = r.route("quarterly earnings and revenue beat", "news", NOW)
    assert res.lead.name == "earnings" and res.how == "matched" and not calls


def test_escalates_then_spawns_new_lead():
    r = router()
    res = r.route("reddit hype twitter", "news", NOW)
    assert res.how == "spawned" and res.lead.name in r.leads


def test_escalation_can_map_rephrasing_to_existing_lead():
    r = router(lambda t, names: "regulatory")
    res = r.route("sebi order", "news", NOW)
    assert res.how in ("matched", "escalated_existing") and res.lead.name == "regulatory"


def test_spawn_needs_domain_manager_approval():
    r = router()
    r.approve_spawn = lambda domain, name: False
    assert r.route("reddit hype", "news", NOW) is None


def test_dormancy_and_rehydration():
    r = router()
    later = NOW + timedelta(weeks=4)
    dormant = r.sweep_dormant(later)
    assert {l.name for l in dormant} == {"earnings", "regulatory"}
    res = r.route("earnings profit", "news", later)
    assert res.how == "rehydrated" and not r.leads["earnings"].dormant
