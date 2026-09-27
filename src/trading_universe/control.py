"""The owner's control room for the agent team (the website's Agents page).

Four files in the run folder, each written by exactly one side so the agent process and the
website never overwrite each other:

  agents.json         written by the agents:  who is doing what right now, plus recent work
  questions.jsonl     written by the agents:  open questions for the owner (append-only)
  controls.json       written by the website: the settings the agents follow (only changed by Apply)
  agent_changes.json  written by the website: suggested changes waiting for Apply, and the history

Flow: the owner suggests a change or answers a question -> it waits in "pending" -> Apply writes it
into controls.json -> the agents pick it up at their next cycle. Every applied change is kept in the
history with what it replaced, so it can be undone.

What can never be changed from here: the ₹200–300 risk per trade, stop-losses, paper vs real money.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .research.sentiment import LEADS

# ------------------------------------------------------------------------------ agent list

CORE = [
    ("orchestrator", "Orchestrator (boss)", "Runs the research cycle every 15 minutes and hands out the work", None),
    ("news_manager", "News manager", "Sorts news to the expert desks, which hire short-lived workers to score it", "orchestrator"),
    ("price_manager", "Price manager", "Reads each coin's chart: trend and volatility", "orchestrator"),
    ("risk_manager", "Risk manager", "Raises danger flags: hacks, delistings, a falling market, wild swings", "orchestrator"),
]
PAUSABLE_PREFIXES = ("lead:", "coin:")
PAUSABLE = {"trading"}
DESK_LABELS = {
    "listings": "Listings", "regulatory": "Regulation", "security": "Hacks & security", "macro": "Macro economy",
    "flows": "Big buyers/sellers", "tech": "Tech upgrades", "social": "Social media", "general": "General",
}


def agent_tree(coins: list[str], custom_desks: dict[str, dict] | None = None) -> list[dict]:
    """Every agent with its label, role and parent, in display order."""
    out = [{"id": i, "label": label, "role": role, "parent": parent, "tier": "core"} for i, label, role, parent in CORE]
    for lead in LEADS:
        out.append({"id": f"lead:{lead.name}", "label": DESK_LABELS.get(lead.name, lead.name.title()), "role": lead.guidance,
                    "parent": "news_manager", "tier": "desk"})
    for name, d in (custom_desks or {}).items():
        out.append({"id": f"lead:{name}", "label": d.get("label") or name.replace("_", " ").title(),
                    "role": d.get("guidance") or d.get("description", ""), "parent": "news_manager", "tier": "desk", "custom": True})
    for c in coins:
        out.append({"id": f"coin:{c}", "label": f"{c.removesuffix('USDT')} agent",
                    "role": f"Combines news, chart and risk flags into one verdict for {c}", "parent": "orchestrator", "tier": "coin"})
    out.append({"id": "trading", "label": "Trading agent", "role": "Every minute: runs the checks, places trades, watches stop-losses",
                "parent": None, "tier": "trading"})
    out.append({"id": "learning", "label": "Learning agent", "role": "Reviews finished trades, writes lessons, suggests improvements",
                "parent": None, "tier": "trading"})
    return out


def is_pausable(agent_id: str) -> bool:
    return agent_id in PAUSABLE or agent_id.startswith(PAUSABLE_PREFIXES)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str))
    tmp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return copy.deepcopy(default)


# --------------------------------------------------------------------------- controls (read)

EMPTY_CONTROLS: dict[str, Any] = {
    "paused": {},         # agent id -> True
    "thresholds": {},     # desk -> {"min_confidence": x, "min_magnitude": y}
    "instructions": {},   # desk -> text
    "rulings": {},        # "item_id:symbol" -> {headline, symbol, direction, lead}
    "refinements": {},    # "sector:event_type" -> confidence multiplier (1.0 = rejected)
    "desks": {},          # custom desk name -> {label, description, guidance}
    "unwatch": {},        # symbol -> time the owner said "stop watching"
    "answered": {},       # question id -> answer
}


@dataclass
class Controls:
    """What the agents follow. Loaded fresh at the start of every cycle."""

    data: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(EMPTY_CONTROLS))

    @classmethod
    def load(cls, path: Path | None) -> Controls:
        if path is None:
            return cls()
        d = _read_json(path, EMPTY_CONTROLS)
        return cls({**copy.deepcopy(EMPTY_CONTROLS), **d})

    def paused(self, agent_id: str) -> bool:
        return bool(self.data["paused"].get(agent_id))

    def threshold(self, desk: str, name: str) -> float | None:
        v = self.data["thresholds"].get(desk, {}).get(name)
        return None if v is None else float(v)

    def instruction(self, desk: str) -> str:
        return self.data["instructions"].get(desk, "")

    def ruling(self, key: str) -> dict | None:
        return self.data["rulings"].get(key)

    def rulings_for(self, desk: str) -> list[dict]:
        return [r for r in self.data["rulings"].values() if r.get("lead") == desk]

    @property
    def refinements(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.data["refinements"].items()}

    @property
    def desks(self) -> dict[str, dict]:
        return self.data["desks"]

    @property
    def unwatch(self) -> dict[str, str]:
        return self.data["unwatch"]

    @property
    def answered(self) -> dict[str, Any]:
        return self.data["answered"]


# ------------------------------------------------------------------------ board (agents write)


class Board:
    """Live status of every agent, written by the agent process."""

    def __init__(self, path: Path | None = None, keep: int = 25) -> None:
        self.path, self.keep = path, keep
        self.data: dict[str, Any] = _read_json(path, {"agents": {}, "cycle": {}}) if path else {"agents": {}, "cycle": {}}

    def _agent(self, agent_id: str) -> dict:
        return self.data["agents"].setdefault(agent_id, {"status": "idle", "doing": "", "updated_at": None, "log": []})

    def set(self, agent_id: str, status: str, doing: str, now: datetime | None = None, **extra: Any) -> None:
        a = self._agent(agent_id)
        a.update(status=status, doing=doing, updated_at=(now or _now()).isoformat(), **extra)

    def log(self, agent_id: str, text: str, now: datetime | None = None) -> None:
        a = self._agent(agent_id)
        a["log"] = ([{"at": (now or _now()).isoformat(), "text": text}] + a["log"])[: self.keep]

    def cycle(self, **info: Any) -> None:
        self.data["cycle"].update(info)

    def flush(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(self.path, self.data)


# -------------------------------------------------------------------- questions (agents write)


class QuestionLog:
    """Open questions from the agents. Each question has a stable id, so it is only asked once."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._ids: set[str] = {q["id"] for q in self.all()}

    def all(self) -> list[dict]:
        if not self.path or not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def ask(self, qid: str, agent: str, kind: str, title: str, detail: str, options: list[str], payload: dict,
            now: datetime | None = None) -> bool:
        """Record a question; False if it was already asked."""
        if qid in self._ids:
            return False
        self._ids.add(qid)
        q = {"id": qid, "agent": agent, "kind": kind, "title": title, "detail": detail, "options": options,
             "payload": payload, "asked_at": (now or _now()).isoformat()}
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(q) + "\n")
        return True

    def asked(self, qid: str) -> bool:
        return qid in self._ids


# ------------------------------------------------------------- changes (the website writes)

LOCKED = "Can't be changed here: the ₹200–300 risk per trade, stop-losses, paper trading vs real money."


class ChangeError(ValueError):
    pass


def _get(d: dict, path: list[str]) -> Any:
    for p in path:
        if not isinstance(d, dict) or p not in d:
            return None
        d = d[p]
    return copy.deepcopy(d)


def _set(d: dict, path: list[str], value: Any) -> None:
    for p in path[:-1]:
        d = d.setdefault(p, {})
    if value is None:
        d.pop(path[-1], None)
    else:
        d[path[-1]] = value


def _clean_desk_name(label: str) -> str:
    name = "".join(ch if ch.isalnum() else "_" for ch in label.strip().lower()).strip("_")
    while "__" in name:
        name = name.replace("__", "_")
    return name[:40]


def change_effects(change: dict) -> list[tuple[list[str], Any]]:
    """The (path in controls.json, new value) pairs a change writes. None deletes the entry."""
    kind, agent, v = change["kind"], change.get("agent", ""), change.get("value")
    qid = change.get("question_id")
    effects: list[tuple[list[str], Any]] = []
    if kind == "pause":
        if not is_pausable(agent):
            raise ChangeError(f"{agent} can't be paused")
        effects.append((["paused", agent], True if v else None))
    elif kind in ("min_confidence", "min_magnitude"):
        if not agent.startswith("lead:"):
            raise ChangeError("strictness can only be set for expert desks")
        if v is not None and not 0 <= float(v) <= 1:
            raise ChangeError("must be between 0 and 1")
        effects.append((["thresholds", agent.removeprefix("lead:"), kind], None if v is None else round(float(v), 3)))
    elif kind == "instruction":
        if not agent.startswith("lead:"):
            raise ChangeError("instructions can only be given to expert desks")
        text = str(v or "").strip()
        if len(text) > 1000:
            raise ChangeError("keep instructions under 1000 characters")
        effects.append((["instructions", agent.removeprefix("lead:")], text or None))
    elif kind == "ruling":  # answer to "is this headline good or bad?"
        if v not in ("bullish", "bearish", "neutral"):
            raise ChangeError("answer must be bullish, bearish or neutral")
        p = change["payload"]
        effects.append((["rulings", p["key"]], {"headline": p["headline"], "symbol": p["symbol"], "direction": v, "lead": p["lead"]}))
    elif kind == "refinement":  # answer to a learning-agent suggestion
        if v not in ("accept", "reject"):
            raise ChangeError("answer must be accept or reject")
        p = change["payload"]
        effects.append((["refinements", p["key"]], float(p["multiplier"]) if v == "accept" else 1.0))
    elif kind == "desk":  # answer to "should there be a new expert desk?"
        if v not in ("approve", "refuse"):
            raise ChangeError("answer must be approve or refuse")
        if v == "approve":
            label = str(change.get("label", "")).strip()
            name = _clean_desk_name(label)
            if not name or f"lead:{name}" in {f"lead:{lead.name}" for lead in LEADS}:
                raise ChangeError("give the new desk a new name")
            desc = str(change.get("description", "")).strip()
            if not desc:
                raise ChangeError("describe what the new desk covers (a few keywords)")
            effects.append((["desks", name], {"label": label, "description": desc,
                                              "guidance": str(change.get("guidance", "")).strip()}))
    elif kind == "unwatch":
        effects.append((["unwatch", agent.removeprefix("coin:")], _now().isoformat()))
    else:
        raise ChangeError(f"unknown change: {kind}")
    if qid:
        effects.append((["answered", qid], v))
    return effects


def display_name(agent: str, controls: dict | None = None) -> str:
    """The name the owner sees: "Social media desk", "SOL agent", "Trading agent"."""
    if agent.startswith("lead:"):
        name = agent.removeprefix("lead:")
        custom = (controls or {}).get("desks", {}).get(name, {})
        return f"{custom.get('label') or DESK_LABELS.get(name, name.title())} desk"
    if agent.startswith("coin:"):
        return f"{agent.removeprefix('coin:').removesuffix('USDT')} agent"
    return next((label for i, label, _, _ in CORE if i == agent), {"trading": "Trading agent", "learning": "Learning agent"}.get(agent, agent))


def describe(change: dict, controls: dict) -> tuple[str, str, str]:
    """(title, before, after) in plain words for the website."""
    kind, agent, v = change["kind"], change.get("agent", ""), change.get("value")
    who = agent.removeprefix("lead:").removeprefix("coin:")
    name = display_name(agent, controls)
    if kind == "pause":
        return f"{name}: {'pause' if v else 'resume'}", "active" if v else "paused", "paused" if v else "active"
    if kind in ("min_confidence", "min_magnitude"):
        before = _get(controls, ["thresholds", who, kind])
        word = "sure" if kind == "min_confidence" else "strong"
        return (f"{name}: news must be at least this {word}", "system default" if before is None else f"{before:.2f}",
                "system default" if v is None else f"{float(v):.2f}")
    if kind == "instruction":
        before = _get(controls, ["instructions", who]) or "(none)"
        return f"{name}: written instruction", before, str(v or "(none)")
    if kind == "ruling":
        return f"Ruling on \"{change['payload']['headline'][:80]}\"", "unsure", str(v)
    if kind == "refinement":
        p = change["payload"]
        return f"Trust {p['event_type']} news on {p['sector']} coins less", "100%", f"{float(p['multiplier']):.0%}" if v == "accept" else "100% (rejected)"
    if kind == "desk":
        return ("New expert desk", "—", change.get("label", "")) if v == "approve" else ("New expert desk", "requested", "refused")
    if kind == "unwatch":
        return f"Trading agent: stop watching {who.removesuffix('USDT')}", "watching", "not watching"
    return kind, "", str(v)


class ChangeBook:
    """Pending suggestions and applied history. Only the website writes these files."""

    def __init__(self, changes_path: Path, controls_path: Path) -> None:
        self.changes_path, self.controls_path = changes_path, controls_path

    def _book(self) -> dict:
        return _read_json(self.changes_path, {"pending": [], "history": []})

    def _controls(self) -> dict:
        return {**copy.deepcopy(EMPTY_CONTROLS), **_read_json(self.controls_path, EMPTY_CONTROLS)}

    def pending(self) -> list[dict]:
        return self._book()["pending"]

    def history(self) -> list[dict]:
        return self._book()["history"]

    def suggest(self, change: dict) -> dict:
        change_effects(change)  # validate now, not at Apply time
        title, before, after = describe(change, self._controls())
        entry = {**change, "id": uuid.uuid4().hex[:10], "title": title, "before": before, "after": after,
                 "suggested_at": _now().isoformat()}
        book = self._book()
        # A newer suggestion for the same thing replaces the older one.
        same = (change["kind"], change.get("agent"), change.get("question_id"))
        book["pending"] = [p for p in book["pending"] if (p["kind"], p.get("agent"), p.get("question_id")) != same] + [entry]
        _write_json(self.changes_path, book)
        return entry

    def drop(self, change_id: str | None = None) -> None:
        book = self._book()
        book["pending"] = [p for p in book["pending"] if change_id is not None and p["id"] != change_id]
        _write_json(self.changes_path, book)

    def apply(self) -> list[dict]:
        book, controls = self._book(), self._controls()
        applied = []
        for change in book["pending"]:
            effects = change_effects(change)
            undo = [(path, _get(controls, path)) for path, _ in effects]
            for path, value in effects:
                _set(controls, path, value)
            applied.append({**change, "applied_at": _now().isoformat(), "undo": undo, "undone_at": None})
        _write_json(self.controls_path, controls)
        book["history"] = (applied[::-1] + book["history"])[:300]
        book["pending"] = []
        _write_json(self.changes_path, book)
        return applied

    def undo(self, change_id: str) -> dict:
        book, controls = self._book(), self._controls()
        entry = next((h for h in book["history"] if h["id"] == change_id), None)
        if entry is None:
            raise ChangeError("no such change")
        if entry.get("undone_at"):
            raise ChangeError("already undone")
        for path, value in entry["undo"]:
            _set(controls, path, value)
        entry["undone_at"] = _now().isoformat()
        _write_json(self.controls_path, controls)
        _write_json(self.changes_path, book)
        return entry
