"""Experiment log (TDD "Experiment Registry & Versioning").

Every time-machine run, edge check or shadow / paper run is written down once, with a unique id: the code
version, what was tested (period, coins, costs, settings, Gemini on/off), the pass/fail rules decided
before the run, and the results. Nothing is ever overwritten (append-only `experiments.jsonl`), so it is
always visible how many variants were tried and how often the hidden exam period has been looked at.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def code_version() -> str:
    try:
        root = Path(__file__).resolve().parents[2]
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root, capture_output=True, text=True, timeout=5)
        return head.stdout.strip() + ("-changed" if dirty.stdout.strip() else "") if head.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class Registry:
    def __init__(self, path: Path) -> None:
        self.path = path

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def exam_views(self, exam_start: str) -> int:
        """How many earlier runs already looked at the same hidden exam period."""
        return sum(1 for e in self.all() if (e.get("period") or {}).get("exam_start") == exam_start)

    def record(self, kind: str, period: dict, coins: list[str], params: dict[str, Any], rules: dict[str, Any],
               results: dict[str, Any], gemini: bool = False, note: str = "") -> dict:
        now = datetime.now(timezone.utc)
        body = json.dumps([kind, period, coins, params, now.isoformat()], sort_keys=True, default=str)
        entry = {
            "id": f"{kind}-{now:%Y%m%d-%H%M%S}-{hashlib.sha1(body.encode()).hexdigest()[:6]}",
            "kind": kind,
            "at": now.isoformat(),
            "code_version": code_version(),
            "period": period,
            "coins": coins,
            "params": params,
            "gemini": gemini,
            "rules": rules,
            "exam_views_before": self.exam_views(period.get("exam_start", "")) if period.get("exam_start") else 0,
            "results": results,
            "note": note,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return entry
