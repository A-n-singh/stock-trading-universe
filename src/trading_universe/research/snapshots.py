"""Where the Orchestrator publishes per-coin snapshots and the Trading Agent reads them."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import AssetClass, Direction, NewsSignal, Snapshot


def snapshot_from_dict(d: dict[str, Any]) -> Snapshot:
    news = d.get("news")
    return Snapshot(
        symbol=d["symbol"],
        direction_bias=Direction(d["direction_bias"]),
        confidence=float(d["confidence"]),
        as_of=datetime.fromisoformat(d["as_of"]),
        asset_class=AssetClass(d.get("asset_class", "crypto")),
        sector=d.get("sector", "unknown"),
        risk_flags=tuple(d.get("risk_flags", ())),
        news=NewsSignal(Direction(news["direction"]), news["magnitude"], news["confidence"], news.get("event_type", "general"),
                        news.get("actionable", False), news.get("headline", "")) if news else None,
        rationale=d.get("rationale", ""),
        snapshot_id=d.get("snapshot_id", ""),
    )


class SnapshotStore:
    """latest.json = newest snapshot per symbol; history.jsonl = every snapshot ever published."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.dir = Path(directory) if directory else None
        self._latest: dict[str, Snapshot] = {}
        if self.dir and (self.dir / "latest.json").exists():
            for d in json.loads((self.dir / "latest.json").read_text()).values():
                s = snapshot_from_dict(d)
                self._latest[s.symbol] = s

    def publish(self, snapshots: list[Snapshot]) -> None:
        for s in snapshots:
            self._latest[s.symbol] = s
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)
            with (self.dir / "history.jsonl").open("a") as f:
                for s in snapshots:
                    f.write(json.dumps(s.to_dict()) + "\n")
            tmp = self.dir / "latest.json.tmp"
            tmp.write_text(json.dumps({k: v.to_dict() for k, v in self._latest.items()}, indent=1))
            tmp.replace(self.dir / "latest.json")  # atomic: the Trading Agent never reads a half-written file

    def latest(self) -> dict[str, Snapshot]:
        if self.dir and (self.dir / "latest.json").exists():  # another process may have published
            self._latest = {d["symbol"]: snapshot_from_dict(d) for d in json.loads((self.dir / "latest.json").read_text()).values()}
        return dict(self._latest)
