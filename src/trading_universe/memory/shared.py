"""The shared memory: one library, one shelf per owner.

Shelves (SDD §Memory Partitioning):
  1. Diary          -> `EventLog` (every event exactly as it happened)
  2. Team lead shelf -> PATTERN records, owner = team lead; general lessons backed by diary events
  3. Coin shelf      -> ASSET_NOTE records, owner = symbol; *links* to patterns instead of copying them
  (+ a per-task `Scratchpad` for workers, thrown away after the task)

Rules enforced here:
  - Every agent gets an `AgentMemory` handle: it can read every shelf but write only its own.
  - No peeking into the future: every read takes `as_of`; records, evidence and results dated
    after it are invisible, so replaying 2020 never sees a lesson learned in 2022.
  - Only proven lessons: a pattern must cite real diary events that happened before it was
    written, and it is retired automatically once real trades keep proving it wrong.
  - The Trading Agent never gets a handle; it reads only the snapshot.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .event_log import EventLog
from .scratchpad import Scratchpad
from .vectors import Embedder, HashEmbedder, InMemoryVectorStore, VectorStore


class Kind(str, Enum):
    PATTERN = "pattern"  # team lead shelf
    ASSET_NOTE = "asset_note"  # coin shelf (one per symbol)


@dataclass
class Outcome:
    ts: datetime
    won: bool
    trade_id: str = ""


@dataclass
class MemoryRecord:
    id: str
    kind: Kind
    owner_id: str
    text: str
    valid_from: datetime  # the moment this lesson was learned
    evidence: list[tuple[str, datetime]] = field(default_factory=list)  # (event_id, date added)
    refs: list[str] = field(default_factory=list)  # pattern ids a coin note points to
    outcomes: list[Outcome] = field(default_factory=list)
    retired_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def visible(self, as_of: datetime) -> bool:
        return self.valid_from <= as_of and (self.retired_at is None or as_of < self.retired_at)

    def record_as_of(self, as_of: datetime) -> tuple[int, int]:
        """(wins, losses) counting only trades that had closed by `as_of`."""
        seen = [o for o in self.outcomes if o.ts <= as_of]
        wins = sum(o.won for o in seen)
        return wins, len(seen) - wins

    def evidence_as_of(self, as_of: datetime) -> list[str]:
        return [eid for eid, added in self.evidence if added <= as_of]


@dataclass(frozen=True)
class Recalled:
    record: MemoryRecord
    score: float
    wins: int
    losses: int

    @property
    def text(self) -> str:
        return self.record.text


@dataclass(frozen=True)
class AssetView:
    symbol: str
    notes: list[str]
    patterns: list[str]  # the linked team-lead lessons, resolved (not copied)


class SharedMemory:
    def __init__(
        self,
        event_log: EventLog,
        embedder: Embedder | None = None,
        store: VectorStore | None = None,
        *,
        dedupe_similarity: float = 0.9,
        min_evidence: int = 2,
        retire_min_trades: int = 10,
        retire_max_loss_rate: float = 0.6,
    ) -> None:
        self.events = event_log
        self.embedder = embedder or HashEmbedder()
        self.store = store or InMemoryVectorStore()
        self.dedupe_similarity = dedupe_similarity
        self.min_evidence = min_evidence
        self.retire_min_trades = retire_min_trades
        self.retire_max_loss_rate = retire_max_loss_rate
        self._records: dict[str, MemoryRecord] = {}
        self._dormant: set[str] = set()

    # ---- handles -----------------------------------------------------------

    def for_agent(self, agent_id: str, writes: Iterable[str] = ()) -> AgentMemory:
        """A handle that can read every shelf but write only to the shelves named in `writes`."""
        return AgentMemory(self, agent_id, frozenset(writes))

    # ---- reads -------------------------------------------------------------

    def get(self, record_id: str) -> MemoryRecord | None:
        return self._records.get(record_id)

    def recall(
        self,
        query: str,
        *,
        kind: Kind,
        as_of: datetime,
        owner_id: str | None = None,
        top_k: int = 5,
        include_dormant: bool = False,
    ) -> list[Recalled]:
        candidates = [
            r.id
            for r in self._records.values()
            if r.kind == kind
            and r.visible(as_of)
            and (owner_id is None or r.owner_id == owner_id)
            and (include_dormant or r.owner_id not in self._dormant)
        ]
        [vec] = self.embedder.embed([query])
        out = []
        for rid, score in self.store.search(vec, candidates)[:top_k]:
            rec = self._records[rid]
            out.append(Recalled(rec, score, *rec.record_as_of(as_of)))
        return out

    def asset_view(self, symbol: str, as_of: datetime) -> AssetView:
        notes = [r for r in self._records.values() if r.kind == Kind.ASSET_NOTE and r.owner_id == symbol and r.visible(as_of)]
        pattern_ids = dict.fromkeys(pid for n in notes for pid in n.refs)
        patterns = [self._records[p].text for p in pattern_ids if p in self._records and self._records[p].visible(as_of)]
        return AssetView(symbol, [n.text for n in notes], patterns)

    # ---- dormancy (archive, never delete) ------------------------------------

    def set_dormant(self, owner_id: str) -> None:
        self._dormant.add(owner_id)

    def rehydrate(self, owner_id: str) -> None:
        self._dormant.discard(owner_id)

    def is_dormant(self, owner_id: str) -> bool:
        return owner_id in self._dormant

    # ---- writes (called through AgentMemory, which checks permissions) -------

    def _nearest_same_shelf(self, text: str, kind: Kind, owner_id: str, as_of: datetime) -> tuple[MemoryRecord | None, list[float]]:
        [vec] = self.embedder.embed([text])
        candidates = [r.id for r in self._records.values() if r.kind == kind and r.owner_id == owner_id and r.visible(as_of)]
        hits = self.store.search(vec, candidates)
        if hits and hits[0][1] >= self.dedupe_similarity:
            return self._records[hits[0][0]], vec
        return None, vec

    def _add_pattern(self, owner_id: str, text: str, evidence_ids: Iterable[str], as_of: datetime, metadata: dict[str, Any] | None) -> MemoryRecord:
        evidence = list(dict.fromkeys(evidence_ids))
        for eid in evidence:
            ev = self.events.get(eid)
            if ev is None:
                raise ValueError(f"evidence {eid!r} is not in the diary")
            if ev.ts > as_of:
                raise ValueError(f"evidence {eid!r} happened after {as_of.isoformat()}: that would be peeking into the future")
        existing, vec = self._nearest_same_shelf(text, Kind.PATTERN, owner_id, as_of)
        if existing is not None:
            # Same lesson said differently: strengthen the existing record instead of piling up duplicates.
            known = {eid for eid, _ in existing.evidence}
            existing.evidence += [(eid, as_of) for eid in evidence if eid not in known]
            return existing
        if len(evidence) < self.min_evidence:
            raise ValueError(f"a lesson needs at least {self.min_evidence} diary events as proof, got {len(evidence)}")
        rec = MemoryRecord(
            id=uuid.uuid4().hex,
            kind=Kind.PATTERN,
            owner_id=owner_id,
            text=text,
            valid_from=as_of,
            evidence=[(eid, as_of) for eid in evidence],
            metadata=dict(metadata or {}),
        )
        self._records[rec.id] = rec
        self.store.upsert(rec.id, vec)
        return rec

    def _add_asset_note(self, symbol: str, text: str, pattern_ids: Iterable[str], as_of: datetime, metadata: dict[str, Any] | None) -> MemoryRecord:
        refs = list(dict.fromkeys(pattern_ids))
        for pid in refs:
            p = self._records.get(pid)
            if p is None or p.kind != Kind.PATTERN or not p.visible(as_of):
                raise ValueError(f"coin note links to unknown or not-yet-learned pattern {pid!r}")
        existing, vec = self._nearest_same_shelf(text, Kind.ASSET_NOTE, symbol, as_of)
        if existing is not None:
            existing.refs += [p for p in refs if p not in existing.refs]
            return existing
        rec = MemoryRecord(uuid.uuid4().hex, Kind.ASSET_NOTE, symbol, text, as_of, refs=refs, metadata=dict(metadata or {}))
        self._records[rec.id] = rec
        self.store.upsert(rec.id, vec)
        return rec

    def _record_outcome(self, pattern_id: str, ts: datetime, won: bool, trade_id: str) -> MemoryRecord:
        rec = self._records[pattern_id]
        if rec.retired_at is not None:
            return rec
        rec.outcomes.append(Outcome(ts, won, trade_id))
        rec.outcomes.sort(key=lambda o: o.ts)
        wins, losses = rec.record_as_of(ts)
        n = wins + losses
        if n >= self.retire_min_trades and losses / n > self.retire_max_loss_rate:
            rec.retired_at = ts  # stops being recalled from this moment on; history is kept
        return rec

    # ---- persistence -----------------------------------------------------------

    def save(self, path: str | Path) -> None:
        def enc(r: MemoryRecord) -> dict[str, Any]:
            return {
                "id": r.id,
                "kind": r.kind.value,
                "owner_id": r.owner_id,
                "text": r.text,
                "valid_from": r.valid_from.isoformat(),
                "evidence": [[e, t.isoformat()] for e, t in r.evidence],
                "refs": r.refs,
                "outcomes": [[o.ts.isoformat(), o.won, o.trade_id] for o in r.outcomes],
                "retired_at": r.retired_at.isoformat() if r.retired_at else None,
                "metadata": r.metadata,
            }

        Path(path).write_text(json.dumps({"records": [enc(r) for r in self._records.values()], "dormant": sorted(self._dormant)}))

    def load(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text())
        dt = datetime.fromisoformat
        for d in data["records"]:
            rec = MemoryRecord(
                id=d["id"],
                kind=Kind(d["kind"]),
                owner_id=d["owner_id"],
                text=d["text"],
                valid_from=dt(d["valid_from"]),
                evidence=[(e, dt(t)) for e, t in d["evidence"]],
                refs=d["refs"],
                outcomes=[Outcome(dt(t), w, tid) for t, w, tid in d["outcomes"]],
                retired_at=dt(d["retired_at"]) if d["retired_at"] else None,
                metadata=d["metadata"],
            )
            self._records[rec.id] = rec
            [vec] = self.embedder.embed([rec.text])
            self.store.upsert(rec.id, vec)
        self._dormant = set(data["dormant"])


class AgentMemory:
    """One agent's view of the shared library: read anything, write only its own shelves."""

    def __init__(self, memory: SharedMemory, agent_id: str, writable: frozenset[str]) -> None:
        self._mem = memory
        self.agent_id = agent_id
        self.writable = writable

    def _check(self, owner_id: str) -> None:
        if owner_id not in self.writable:
            raise PermissionError(f"{self.agent_id} may not write to the {owner_id!r} shelf")

    # reads
    def recall_patterns(self, query: str, as_of: datetime, owner_id: str | None = None, top_k: int = 5) -> list[Recalled]:
        return self._mem.recall(query, kind=Kind.PATTERN, as_of=as_of, owner_id=owner_id, top_k=top_k)

    def recall_asset_notes(self, query: str, as_of: datetime, symbol: str | None = None, top_k: int = 5) -> list[Recalled]:
        return self._mem.recall(query, kind=Kind.ASSET_NOTE, as_of=as_of, owner_id=symbol, top_k=top_k)

    def asset_view(self, symbol: str, as_of: datetime) -> AssetView:
        return self._mem.asset_view(symbol, as_of)

    def events(self, symbol: str | None, as_of: datetime):
        return self._mem.events.events(symbol=symbol, as_of=as_of)

    # writes
    def add_pattern(self, owner_id: str, text: str, evidence_ids: Iterable[str], as_of: datetime, metadata: dict[str, Any] | None = None) -> MemoryRecord:
        self._check(owner_id)
        return self._mem._add_pattern(owner_id, text, evidence_ids, as_of, metadata)

    def add_asset_note(self, symbol: str, text: str, pattern_ids: Iterable[str], as_of: datetime, metadata: dict[str, Any] | None = None) -> MemoryRecord:
        self._check(symbol)
        return self._mem._add_asset_note(symbol, text, pattern_ids, as_of, metadata)

    def record_outcome(self, pattern_id: str, ts: datetime, won: bool, trade_id: str = "") -> MemoryRecord:
        rec = self._mem.get(pattern_id)
        if rec is None:
            raise KeyError(pattern_id)
        self._check(rec.owner_id)
        return self._mem._record_outcome(pattern_id, ts, won, trade_id)

    def scratchpad(self, task: str) -> Scratchpad:
        return Scratchpad(task)
