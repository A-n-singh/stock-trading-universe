from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import NOW
from trading_universe.memory import EventLog, Kind, MarketEvent, SharedMemory
from trading_universe.memory.vectors import HashEmbedder
from trading_universe.research.team_leads import TeamLeadRouter

D = timedelta(days=1)
EARNINGS = "earnings beat usually leads to a price rise over the next two days"


def diary(tmp_path: Path | None = None) -> EventLog:
    log = EventLog(tmp_path / "events.jsonl" if tmp_path else None)
    for i, sym in enumerate(["INFY", "TCS", "WIPRO"]):
        log.append(MarketEvent(f"e{i}", sym, NOW + i * D, "earnings", f"{sym} beat estimates, stock +3%", sector="it"))
    log.append(MarketEvent("future", "HCL", NOW + 400 * D, "earnings", "HCL beat estimates"))
    return log


@pytest.fixture
def mem() -> SharedMemory:
    return SharedMemory(diary(), retire_min_trades=4, retire_max_loss_rate=0.5)


def lead(mem: SharedMemory):
    return mem.for_agent("earnings-lead", writes={"earnings-lead"})


def test_each_agent_writes_only_its_own_shelf(mem):
    other = mem.for_agent("regulatory-lead", writes={"regulatory-lead"})
    with pytest.raises(PermissionError):
        other.add_pattern("earnings-lead", EARNINGS, ["e0", "e1"], NOW + 5 * D)
    rec = lead(mem).add_pattern("earnings-lead", EARNINGS, ["e0", "e1"], NOW + 5 * D)
    # ...but everyone can read every shelf.
    assert other.recall_patterns("earnings beat", NOW + 6 * D)[0].record.id == rec.id


def test_no_peeking_into_the_future(mem):
    lead(mem).add_pattern("earnings-lead", EARNINGS, ["e0", "e1"], NOW + 5 * D)
    reader = mem.for_agent("worker")
    assert reader.recall_patterns("earnings beat", NOW + 4 * D) == []  # lesson not learned yet
    assert len(reader.recall_patterns("earnings beat", NOW + 5 * D)) == 1
    assert [e.event_id for e in reader.events(None, NOW + D)] == ["e0", "e1"]


def test_lesson_cannot_cite_future_or_missing_events(mem):
    with pytest.raises(ValueError, match="future"):
        lead(mem).add_pattern("earnings-lead", EARNINGS, ["e0", "future"], NOW + 5 * D)
    with pytest.raises(ValueError, match="not in the diary"):
        lead(mem).add_pattern("earnings-lead", EARNINGS, ["e0", "made-up"], NOW + 5 * D)


def test_lesson_needs_enough_proof(mem):
    with pytest.raises(ValueError, match="at least 2"):
        lead(mem).add_pattern("earnings-lead", EARNINGS, ["e0"], NOW + 5 * D)


def test_same_lesson_twice_is_merged_not_duplicated(mem):
    a = lead(mem).add_pattern("earnings-lead", EARNINGS, ["e0", "e1"], NOW + 5 * D)
    b = lead(mem).add_pattern("earnings-lead", EARNINGS.replace("usually", "often"), ["e2"], NOW + 6 * D)
    assert a.id == b.id
    assert a.evidence_as_of(NOW + 5 * D) == ["e0", "e1"]
    assert a.evidence_as_of(NOW + 6 * D) == ["e0", "e1", "e2"]


def test_losing_lesson_is_retired_from_that_moment_on(mem):
    rec = lead(mem).add_pattern("earnings-lead", EARNINGS, ["e0", "e1"], NOW + 5 * D)
    for i, won in enumerate([True, False, False, False]):
        lead(mem).record_outcome(rec.id, NOW + (10 + i) * D, won, f"t{i}")
    assert rec.retired_at == NOW + 13 * D
    reader = mem.for_agent("worker")
    assert len(reader.recall_patterns("earnings", NOW + 12 * D)) == 1  # replaying earlier still sees it
    assert reader.recall_patterns("earnings", NOW + 13 * D) == []
    assert reader.recall_patterns("earnings", NOW + 11 * D)[0].losses == 1


def test_stock_note_links_to_pattern_instead_of_copying(mem):
    p = lead(mem).add_pattern("earnings-lead", EARNINGS, ["e0", "e1"], NOW + 5 * D)
    infy = mem.for_agent("cluster:INFY", writes={"INFY"})
    infy.add_stock_note("INFY", "INFY reacts a day late to earnings news", [p.id], NOW + 6 * D)
    view = infy.stock_view("INFY", NOW + 7 * D)
    assert view.notes == ["INFY reacts a day late to earnings news"]
    assert view.patterns == [EARNINGS]
    with pytest.raises(ValueError, match="not-yet-learned"):
        infy.add_stock_note("INFY", "something else entirely", [p.id], NOW + 4 * D)
    with pytest.raises(PermissionError):
        infy.add_stock_note("TCS", "note", [], NOW + 6 * D)


def test_dormant_shelf_follows_team_lead(mem):
    lead(mem).add_pattern("earnings-lead", EARNINGS, ["e0", "e1"], NOW + 5 * D)
    emb = HashEmbedder()
    router = TeamLeadRouter(embed=lambda t: emb.embed([t])[0], escalate=lambda t, n: None, threshold=0.5, memory=mem)
    router.add_lead("earnings-lead", "news", ["earnings beat estimates"], NOW)
    router.sweep_dormant(NOW + 30 * D)
    assert mem.is_dormant("earnings-lead")
    assert mem.recall("earnings", kind=Kind.PATTERN, as_of=NOW + 30 * D) == []
    router.route("earnings beat estimates again", "news", NOW + 31 * D)
    assert not mem.is_dormant("earnings-lead")
    assert len(mem.recall("earnings", kind=Kind.PATTERN, as_of=NOW + 31 * D)) == 1


def test_scratchpad_is_per_task_and_disposable(mem):
    pad = mem.for_agent("worker-1").scratchpad("check INFY filing")
    pad.add("x" * 2000)
    assert pad.notes[0].endswith("[truncated]")
    assert mem.for_agent("worker-1").scratchpad("other task").notes == []


def test_diary_is_append_only_and_persists(tmp_path):
    log = diary(tmp_path)
    with pytest.raises(ValueError):
        log.append(MarketEvent("e0", "INFY", NOW, "earnings", "dup"))
    assert len(EventLog(tmp_path / "events.jsonl")) == 4


def test_memory_save_and_load(tmp_path, mem):
    p = lead(mem).add_pattern("earnings-lead", EARNINGS, ["e0", "e1"], NOW + 5 * D)
    lead(mem).record_outcome(p.id, NOW + 6 * D, True)
    mem.set_dormant("regulatory-lead")
    mem.save(tmp_path / "mem.json")
    fresh = SharedMemory(mem.events)
    fresh.load(tmp_path / "mem.json")
    hits = fresh.recall("earnings", kind=Kind.PATTERN, as_of=NOW + 7 * D)
    assert hits[0].record.id == p.id and hits[0].wins == 1
    assert fresh.is_dormant("regulatory-lead")


def test_trading_agent_never_touches_memory():
    """The fast loop reads only the snapshot; it must not import the memory package."""
    pkg = Path(__file__).parents[1] / "src" / "trading_universe" / "trading_agent"
    for f in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert "memory" not in (node.module or ""), f"{f.name} imports memory"
