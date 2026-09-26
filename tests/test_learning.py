from __future__ import annotations

from datetime import timedelta

from conftest import NOW, snapshot
from trading_universe.learning import MistakeLoop, Refinements
from trading_universe.memory import EventLog, Kind, SharedMemory
from trading_universe.models import Action, GateVote, TradeDecision
from trading_universe.trade_log import TradeLog


def closed_trades(moves: list[float], event_type: str = "listing", symbol: str = "SOLUSDT") -> TradeLog:
    log = TradeLog()
    for i, move in enumerate(moves):
        snap = snapshot(symbol, snapshot_id=f"s{i}", event_type=event_type)
        d = TradeDecision(symbol, Action.BUY, 1, 100.0, 97.0, 3.0, (GateVote("news", True),), snap, NOW + timedelta(days=i))
        log.record_open(f"t{i}", d, 100.0, 0.0)
        log.record_close(f"t{i}", 100.0 + move, NOW + timedelta(days=i, hours=5), "test", 0.0)
    return log


def test_consistent_results_become_a_proven_lesson_with_coin_note():
    mem = SharedMemory(EventLog())
    loop = MistakeLoop(mem, closed_trades([4, 5, -3]), Refinements())
    rep = loop.run(NOW + timedelta(days=5))
    assert rep.trades_learned == 3 and len(rep.lessons_written) == 1
    assert "listing" in rep.lessons_written[0] and "2/3 won" in rep.lessons_written[0]
    (lesson,) = mem.recall("listing", kind=Kind.PATTERN, as_of=NOW + timedelta(days=5))
    assert lesson.record.owner_id == "listings" and len(lesson.record.evidence) == 3  # backed by 3 trade outcomes
    assert mem.asset_view("SOLUSDT", NOW + timedelta(days=5)).patterns == [lesson.text]
    assert loop.run(NOW + timedelta(days=6)).trades_learned == 0  # each trade is learned once


def test_mixed_results_write_no_lesson():
    mem = SharedMemory(EventLog())
    rep = MistakeLoop(mem, closed_trades([4, -3, 5, -3]), Refinements(), min_agreement=0.7).run(NOW + timedelta(days=5))
    assert rep.lessons_written == []


def test_losing_cluster_gets_its_confidence_cut_and_a_task():
    ref = Refinements()
    MistakeLoop(SharedMemory(EventLog()), closed_trades([-3] * 5 + [2]), ref).run(NOW + timedelta(days=9))
    assert ref.factor("layer1", "listing") == 0.6
    assert ref.tasks and ref.tasks[0]["lead"] == "listings"
    assert ref.factor("layer1", "hack") == 1.0  # only the losing cluster is touched
